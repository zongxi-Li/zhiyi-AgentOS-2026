"""Native desktop development lifecycle; execution stays in the production apps.

PostgreSQL/Redis remain in Docker. A loopback stdio relay uses the existing
PostgreSQL container's nc, retaining database authentication and unpublished
container ports. New runs own separate PostgreSQL roles/databases and SQLite.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time

import native_runtime as native

ROOT = native.ROOT
POSTGRES = 'kinlin-win-p1-001-postgres-1'
SECRETS = ROOT / '.secrets/kinlin-win-p1-001'


def relay(port, target, target_port):
    stopping = threading.Event()
    connections = set()
    processes = set()
    def shutdown(*_args):
        stopping.set()
        for connection in list(connections):
            try: connection.shutdown(socket.SHUT_RDWR)
            except OSError: pass
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGBREAK, shutdown)
    def serve(connection):
        connections.add(connection)
        child = subprocess.Popen(['docker', 'exec', '-i', POSTGRES, 'nc', target, str(target_port)],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        processes.add(child)
        def upload():
            try:
                while data := connection.recv(65536):
                    child.stdin.write(data)
                    child.stdin.flush()
            except (OSError, ValueError): pass
            finally:
                try: child.stdin.close()
                except OSError: pass
        threading.Thread(target=upload, daemon=True).start()
        try:
            while data := child.stdout.read1(65536): connection.sendall(data)
        except OSError: pass
        finally:
            connection.close()
            connections.discard(connection)
            try: child.wait(5)
            except subprocess.TimeoutExpired: child.terminate(); child.wait(5)
            processes.discard(child)
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(('127.0.0.1', port))
        listener.listen()
        listener.settimeout(.3)
        while not stopping.is_set():
            try: connection, _address = listener.accept()
            except socket.timeout: continue
            threading.Thread(target=serve, args=(connection,), daemon=True).start()
    shutdown()
    deadline = time.monotonic() + 8
    while processes and time.monotonic() < deadline: time.sleep(.1)


def save(run, state): native.write_json(run / 'desktop-state.json', state)


def spawn_app(run, name, command, env, cwd):
    import psutil
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = subprocess.SW_HIDE
    with (run / f'{name}.log').open('ab') as log:
        child = subprocess.Popen(command,cwd=cwd,env=env,stdout=log,stderr=log,
                                 creationflags=subprocess.CREATE_NEW_CONSOLE,startupinfo=info)
    return native.identity(psutil.Process(child.pid))


def show_desktop(record):
    """The interactive app window is visible; its helper console stays hidden."""
    import win32con
    import win32gui
    import win32process
    parent=native.owned(record)
    pids={p.pid for p in [parent,*parent.children(recursive=True)]}
    windows=[]
    def visit(hwnd,_context):
        _thread,pid=win32process.GetWindowThreadProcessId(hwnd)
        if pid in pids and win32gui.GetClassName(hwnd)=='Tauri Window':
            win32gui.ShowWindow(hwnd,win32con.SW_RESTORE)
            try: win32gui.SetForegroundWindow(hwnd)
            except Exception: pass
            windows.append({'pid':pid,'handle':hwnd,'visible':bool(win32gui.IsWindowVisible(hwnd))})
    win32gui.EnumWindows(visit,None)
    return windows


def close_desktop(record):
    """Close only windows descended from this lifecycle's verified owner."""
    import win32con
    import win32gui
    import win32process
    parent = native.owned(record)
    if parent is None: return
    pids = {p.pid for p in [parent, *parent.children(recursive=True)]}
    def visit(hwnd, _context):
        _thread, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid in pids and win32gui.GetClassName(hwnd) == 'Tauri Window':
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    win32gui.EnumWindows(visit, None)
    deadline = time.monotonic() + 12
    while native.owned(record) and time.monotonic() < deadline: time.sleep(.2)


def env_for(run, state, creds):
    env = native.environment(run, state, creds)
    env.update({
        'NO_PROXY': '127.0.0.1,localhost',
        'ZHIYI_LOCAL_RUNTIME_WORKSPACE_ROOT': state['workspace'], 'TOOL_CODEBASE_ROOT': state['workspace'],
        'DEEPSEEK_API_KEY_FILE': str(SECRETS / 'deepseek_api_key'),
        'DEEPSEEK_BASE_URL': 'https://api.deepseek.com', 'DEEPSEEK_MODEL': 'deepseek-chat',
        'AGENTOS_LLM_PROVIDER': 'deepseek', 'AGENTOS_LLM_MODEL': 'deepseek-chat',
        'TEXT_ENGINE': 'deepseek', 'DEEPSEEK_ENABLED': 'true',
    })
    return env


def java_environment(run, state, creds):
    return dict(env_for(run,state,creds),
                SPRING_DATASOURCE_URL=f"jdbc:postgresql://127.0.0.1:15432/{state['database']}",
                SPRING_DATASOURCE_USERNAME=state['database'],SPRING_DATASOURCE_PASSWORD=creds['db'],
                SPRING_REDIS_HOST='127.0.0.1',SPRING_REDIS_PORT='16379',
                SPRING_REDIS_DATABASE=str(state['redisDatabase']),
                SPRING_REDIS_PASSWORD=(SECRETS/'redis_password').read_text().strip(),
                APP_JWT_SECRET=creds['jwt'],AI_INTERNAL_TOKEN=creds['token'],AI_INTERNAL_REQUIRED='true',
                AI_SERVICE_URL='http://127.0.0.1:18761',SERVER_PORT='18080',SERVER_ADDRESS='127.0.0.1',
                CORS_ALLOWED_ORIGINS='http://127.0.0.1:15200,http://tauri.localhost,tauri://localhost',
                APP_UPLOAD_DIR=str(run/'uploads'),SPRING_DATASOURCE_HIKARI_MAXIMUM_POOL_SIZE='3',
                SPRING_DATASOURCE_HIKARI_MINIMUM_IDLE='1')


def wait_until(check, process, timeout=90):
    import redis
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if native.owned(process) is None: raise RuntimeError('Owned process exited; inspect its log')
        try:
            result = check()
            if result: return result
        except (OSError, ValueError, redis.exceptions.ConnectionError): pass
        time.sleep(.5)
    raise RuntimeError('Service readiness timed out')


def up(run, workspace, desktop):
    native.preflight(run, 18761, 18765)
    for port in [18080, 15200, 15432, 16379]: native.port_free(port)
    if desktop: native.port_free(19222)
    workspace = workspace.resolve(strict=True) if workspace else run / 'workspace'
    if workspace.exists() and (not workspace.is_dir() or workspace.is_junction() or workspace.is_symlink()):
        raise RuntimeError('Workspace must be a real directory')
    jar = ROOT / 'apps/backend/target/kinlin-backend-1.0.0.jar'
    if not jar.is_file(): raise RuntimeError('Build Backend first: mvn -DskipTests package')
    run.mkdir(parents=True)
    for path in [run/'temp', workspace]: path.mkdir(exist_ok=True)
    (run/'.env').write_text('', encoding='utf-8')
    creds = {name: secrets.token_hex(32) for name in ['hmac','token','db','jwt','test_password']}
    creds['key'] = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
    (run/'credentials.dpapi').write_bytes(native.dpapi(json.dumps(creds).encode()))
    identifier = 'n02_' + secrets.token_hex(5)
    state = {'format':'kinlin-native-desktop-v1','runDirectory':str(run),'workspace':str(workspace),
             'aiPort':18761,'hostPort':18765,'javaPort':18080,'frontendPort':15200,
             'database':identifier,'processes':{},'created':time.time(),'desktop':desktop}
    save(run,state)
    try:
        sql = f"CREATE ROLE {identifier} LOGIN PASSWORD '{creds['db']}';\nCREATE DATABASE {identifier} OWNER {identifier};\n"
        result = subprocess.run(['docker','exec','-i',POSTGRES,'psql','-U','postgres','-v','ON_ERROR_STOP=1','-q'],
                                input=sql,text=True,capture_output=True)
        if result.returncode: raise RuntimeError('Isolated database provisioning failed: '+result.stderr)
        state['databaseCreated'] = True; save(run,state)
        env = env_for(run,state,creds)
        for name, port, host, target_port in [('postgres-relay',15432,'127.0.0.1',5432),('redis-relay',16379,'redis',6379)]:
            record = native.spawn(run,name,[sys.executable,str(Path(__file__).resolve()),'_relay',str(port),host,str(target_port)],env)
            state['processes'][name]=record; save(run,state)
        import redis
        redis_password = (SECRETS/'redis_password').read_text().strip()
        client = redis.Redis(host='127.0.0.1',port=16379,password=redis_password,db=15)
        wait_until(lambda: client.ping(), state['processes']['redis-relay'])
        for candidate in range(15, 1, -1):
            client.execute_command('SELECT',candidate)
            if client.dbsize() == 0:
                state['redisDatabase']=candidate
                save(run,state)
                break
        else: raise RuntimeError('No unused test Redis database available; no existing data was cleared')
        client.close()
        native.prepare(run,env,'ai')
        local_env=dict(env,PYTHONPATH=os.pathsep.join([str(ROOT/'apps/local-runtime'),str(ROOT/'apps/agentOS/src')]))
        for name,command,child_env in [
            ('host',[sys.executable,'-m','runtime.main'],local_env),
            ('ai',[sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port','18761','--workers','1'],env),
        ]:
            state['processes'][name]=native.spawn(run,name,command,child_env); save(run,state)
        wait_until(lambda: native.health(18761,'/health/ready').get('status')=='UP',state['processes']['ai'],180)
        java_env=java_environment(run,state,creds)
        state['processes']['java']=native.spawn(run,'java',[shutil.which('java'),'-jar',str(jar)],java_env); save(run,state)
        wait_until(lambda: native.health(18080,'/actuator/health/readiness').get('status')=='UP',state['processes']['java'],150)
        front_env={key:value for key,value in env.items() if key in {
            'SYSTEMROOT','WINDIR','COMSPEC','PATH','PATHEXT','USERPROFILE','APPDATA','LOCALAPPDATA',
            'PROGRAMDATA','TEMP','TMP','PYTHONUTF8','NO_PROXY'}}
        front_env.update(DEV_BACKEND_PROXY_TARGET='http://127.0.0.1:18080',VITE_API_BASE_URL='')
        state['processes']['frontend']=native.spawn(run,'frontend',[shutil.which('node'),str(ROOT/'apps/frontend/node_modules/vite/bin/vite.js'),
            str(ROOT/'apps/frontend'),'--mode','desktop','--host','127.0.0.1','--port','15200'],front_env); save(run,state)
        wait_until(lambda: socket.create_connection(('127.0.0.1',15200),timeout=1).close() is None,state['processes']['frontend'])
        if desktop:
            desktop_env=dict(front_env,WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS='--remote-debugging-port=19222',
                             WEBVIEW2_USER_DATA_FOLDER=str(run/'webview'))
            for key in ['CARGO_HOME','RUSTUP_HOME','CARGO_TARGET_DIR','VSINSTALLDIR']:
                if os.getenv(key): desktop_env[key]=os.environ[key]
            config=run/'tauri-native.json'
            native.write_json(config,{'identifier':'com.kinlin.zhiyi.native-dev',
                                      'build':{'beforeDevCommand':'','devUrl':'http://127.0.0.1:15200'}})
            command=[shutil.which('node'),str(ROOT/'apps/desktop/node_modules/@tauri-apps/cli/tauri.js'),
                     'dev','--config',str(config),'--no-watch','--','--bin','kinlin-native-dev']
            state['processes']['desktop']=spawn_app(run,'desktop',command,desktop_env,ROOT/'apps/desktop'); save(run,state)
            wait_until(lambda: native.health(19222,'/json/version'),state['processes']['desktop'],240)
            state['desktopWindows']=show_desktop(state['processes']['desktop']); save(run,state)
        native.write_json(run/'desktop-up.json',status(run,state))
        return status(run,state)
    except BaseException:
        down(run,state)
        raise


def status(run,state):
    result={'services':{},'runtime':native.snapshot(state),'workspace':state['workspace'],'database':state['database']}
    for name,record in state['processes'].items():
        result['services'][name] = {'alive':native.owned(record) is not None,'process':record}
    try: result['javaHealth']=native.health(18080,'/actuator/health')
    except OSError: result['javaHealth']={'status':'DOWN'}
    result['status']='UP' if result['runtime']['coreReady'] and result['javaHealth']['status']=='UP' and all(v['alive'] for v in result['services'].values()) else 'DOWN'
    return result


def down(run,state):
    errors=[]
    for name,record in reversed(list(state['processes'].items())):
        try:
            if name == 'desktop': close_desktop(record)
            native.stop(record)
        except Exception as exc: errors.append({'service':name,'error':str(exc)})
    if errors:
        native.write_json(run/'desktop-down-errors.json',errors)
        raise RuntimeError('Shutdown errors; retained credentials and process evidence')
    for port in [18761,18765,18080,15200,15432,16379]: native.port_free(port)
    if state.get('desktop'): native.port_free(19222)
    # Reuse N01A's real Windows lock and exclusive SQLite handle verification.
    runtime_cleanup = native.down(run,state)
    result={'status':'PASS','processesAbsent':all(native.owned(r) is None for r in state['processes'].values()),
            'portsReleased':True,'credentialsRemoved':True,'testDatabaseRetained':state['database'],
            'runtimeCleanup':runtime_cleanup}
    native.write_json(run/'desktop-down.json',result)
    return result


def main():
    if len(sys.argv)==5 and sys.argv[1]=='_relay':
        relay(int(sys.argv[2]),sys.argv[3],int(sys.argv[4])); return
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['up','status','down'])
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--workspace',type=Path)
    parser.add_argument('--desktop',action='store_true')
    args=parser.parse_args()
    if not args.run_dir.is_absolute(): parser.error('Absolute run directory required')
    run=args.run_dir
    if args.action=='up': result=up(run,args.workspace,args.desktop)
    else:
        state=native.read_json(run/'desktop-state.json')
        if state.get('format')!='kinlin-native-desktop-v1' or state['runDirectory']!=str(run): raise RuntimeError('Invalid lifecycle ownership')
        result=status(run,state) if args.action=='status' else down(run,state)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return int(result.get('status')=='DOWN')


if __name__=='__main__': raise SystemExit(main())
