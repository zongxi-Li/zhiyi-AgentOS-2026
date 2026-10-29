"""User-owned persistent Windows deployment of the existing production apps.

No Windows services, firewall rules, Docker CLI, alternate executor or workflow
database are installed. init creates identities once; up never rotates them.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time

import native_runtime as native
import desktop_runtime as desktop

ROOT = native.ROOT
PORTS = [15432, 16379, 18761, 18765, 18080, 15200, 19222]
FORMAT = 'zhiyi-windows-persistent-v1'


def protect(directory):
    """Restrict only this newly created user-owned directory; never broaden ACLs."""
    import win32api
    import win32security
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32security.TOKEN_QUERY)
    try:
        sid = win32security.ConvertSidToStringSid(win32security.GetTokenInformation(token, win32security.TokenUser)[0])
    finally:
        token.Close()
    subprocess.run(['icacls', str(directory), '/inheritance:r', '/grant:r',
                    f'*{sid}:(OI)(CI)F', '*S-1-5-18:(OI)(CI)F'], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def validate_home(home):
    if os.name != 'nt' or sys.version_info[:2] != (3, 14):
        raise RuntimeError('Real Windows CPython 3.14 required')
    token = native.windows_token(os.getpid())
    if token['elevated'] or int(token['integritySid'].rsplit('-', 1)[1]) > 8192:
        raise RuntimeError('Run as an ordinary non-elevated Windows user')
    if not home.is_absolute() or home.resolve().is_relative_to(ROOT.resolve()):
        raise RuntimeError('Persistent home must be an absolute path outside the repository')
    for part in [home, *home.parents]:
        if part.is_symlink() or part.is_junction():
            raise RuntimeError('Persistent home may not traverse reparse directories')


def manifest(home):
    value = native.read_json(home / 'environment.json')
    if value.get('format') != FORMAT or value['home'] != str(home):
        raise RuntimeError('Persistent home identity mismatch; no data was changed')
    return value


def state_for(home):
    path = home / 'runtime-state.json'
    return native.read_json(path) if path.exists() else {
        'format': FORMAT, 'runDirectory': str(home), 'aiPort': 18761,
        'hostPort': 18765, 'processes': {}, 'desktop': False,
    }


def save(home, state):
    temporary = home / 'runtime-state.next.json'
    native.write_json(temporary, state)
    temporary.replace(home / 'runtime-state.json')


def env_for(home, info, creds):
    env = native.environment(home, state_for(home), creds)
    env.update({
        'NO_PROXY': '127.0.0.1,localhost',
        'ZHIYI_LOCAL_RUNTIME_WORKSPACE_ROOT': info['workspace'],
        'TOOL_CODEBASE_ROOT': info['workspace'],
        'DEEPSEEK_API_KEY': creds['deepseek'], 'DEEPSEEK_BASE_URL': 'https://api.deepseek.com',
        'DEEPSEEK_MODEL': 'deepseek-chat', 'AGENTOS_LLM_PROVIDER': 'deepseek',
        'AGENTOS_LLM_MODEL': 'deepseek-chat', 'TEXT_ENGINE': 'deepseek', 'DEEPSEEK_ENABLED': 'true',
        'REDIS_PASSWORD': creds['redis'],
        'AGENTOS_COORDINATION_REDIS_URL': 'redis://127.0.0.1:16379/1',
        'PROVIDER_STATE_REDIS_URL': 'redis://127.0.0.1:16379/2',
    })
    return env


def java_environment(home, info, creds):
    return dict(env_for(home, info, creds),
        SPRING_DATASOURCE_URL='jdbc:postgresql://127.0.0.1:15432/zhiyi',
        SPRING_DATASOURCE_USERNAME='zhiyi_app', SPRING_DATASOURCE_PASSWORD=creds['db'],
        SPRING_REDIS_HOST='127.0.0.1', SPRING_REDIS_PORT='16379', SPRING_REDIS_DATABASE='0',
        SPRING_REDIS_PASSWORD=creds['redis'], APP_JWT_SECRET=creds['jwt'],
        AI_INTERNAL_REQUIRED='true', AI_SERVICE_URL='http://127.0.0.1:18761',
        SERVER_PORT='18080', SERVER_ADDRESS='127.0.0.1',
        CORS_ALLOWED_ORIGINS='http://127.0.0.1:15200,http://tauri.localhost,tauri://localhost',
        APP_UPLOAD_DIR=str(home/'uploads'), SPRING_DATASOURCE_HIKARI_MAXIMUM_POOL_SIZE='3',
        SPRING_DATASOURCE_HIKARI_MINIMUM_IDLE='1')


def pg_env(creds):
    return dict(os.environ, PGHOST='127.0.0.1', PGPORT='15432', PGUSER='zhiyi_admin',
                PGPASSWORD=creds['pgadmin'], PGDATABASE='postgres', PGCLIENTENCODING='UTF8')


def sql(info, creds, text):
    result = subprocess.run([str(Path(info['postgresBin'])/'psql.exe'), '-X', '-q', '-t', '-A',
                             '-v', 'ON_ERROR_STOP=1'], input=text, text=True, encoding='utf-8',
                            capture_output=True, env=pg_env(creds))
    if result.returncode:
        # DDL errors can echo a password literal; never expose that stderr.
        raise RuntimeError('Native PostgreSQL administrative command failed')
    return result.stdout.strip()


def redis_client(creds, db=0):
    import redis
    return redis.Redis(host='127.0.0.1', port=16379, password=creds['redis'],
                       db=db, socket_timeout=3, socket_connect_timeout=3)


def alive(record):
    try: return native.owned(record)
    except RuntimeError: return None  # recycled PID belongs to someone else


def init(home, args):
    if (home/'environment.json').exists():
        manifest(home)
        return {'status': 'READY', 'initializedNow': False, 'home': str(home)}
    if any(home.iterdir()):
        raise RuntimeError('Refusing to initialize a nonempty unrecognized home')
    pg = args.postgres_bin.resolve(strict=True)
    memurai = args.memurai.resolve(strict=True)
    for name in ['postgres.exe', 'initdb.exe', 'pg_ctl.exe', 'psql.exe']:
        if not (pg/name).is_file(): raise RuntimeError(f'Missing PostgreSQL executable: {name}')
    keyfile = args.provider_key_file or ROOT/'.secrets/kinlin-win-p1-001/deepseek_api_key'
    key = keyfile.read_text(encoding='utf-8').strip()
    if not key: raise RuntimeError('Configure a real provider key before initialization')
    workspace = args.workspace.resolve(strict=True) if args.workspace else home/'workspace'
    if workspace.exists() and (not workspace.is_dir() or workspace.is_symlink() or workspace.is_junction()):
        raise RuntimeError('Workspace must be a real directory')
    protect(home)
    for path in [home/'temp', home/'logs', home/'redis', workspace]: path.mkdir(exist_ok=True)
    (home/'.env').write_text('', encoding='utf-8')
    creds = {name: secrets.token_hex(32) for name in ['pgadmin','db','redis','jwt','token','hmac','test_password']}
    creds.update(key=base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(), deepseek=key)
    (home/'credentials.dpapi').write_bytes(native.dpapi(json.dumps(creds).encode()))
    info = {'format': FORMAT, 'home': str(home), 'workspace': str(workspace),
            'postgresBin': str(pg), 'memurai': str(memurai), 'database': 'zhiyi', 'databaseRole': 'zhiyi_app',
            'redisDatabases': {'java': 0, 'coordination': 1, 'providerState': 2},
            'created': datetime.now(timezone.utc).isoformat(),
            'redisLicense': 'Memurai Developer; development/testing only; 10-day maximum uptime',
            'initialized': False}
    native.write_json(home/'environment.json', info)
    save(home, state_for(home))
    return {'status': 'READY', 'initializedNow': True, 'home': str(home), 'workspace': str(workspace)}


def schema(home, env, first):
    if first:
        native.prepare(home, env, 'logs/initialize')
    else:
        command = [sys.executable, str(ROOT/'scripts/prepare_agentos_runtime.py')]
        with (home/'logs/schema-inspect.log').open('ab') as log:
            subprocess.run(command, cwd=home, env=env, stdout=log, stderr=log, check=True)


def up(home, use_desktop):
    info, creds, state = manifest(home), native.credentials(home), state_for(home)
    workspace = Path(info['workspace'])
    if not workspace.is_dir() or workspace.is_symlink() or workspace.is_junction() or str(workspace.resolve()) != info['workspace']:
        raise RuntimeError('Startup-issued workspace root changed; refusing to reissue authority')
    if any(alive(record) for record in state['processes'].values()):
        raise RuntimeError('This persistent environment already owns running processes; use status or recover')
    for port in PORTS if use_desktop else PORTS[:-1]: native.port_free(port)
    if not (ROOT/'apps/backend/target/kinlin-backend-1.0.0.jar').is_file():
        raise RuntimeError('Build the Java backend first: mvn -DskipTests package')
    session = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+secrets.token_hex(2)
    logdir = home/'logs'/session
    logdir.mkdir()
    state.update(processes={}, desktop=use_desktop, session=session)
    save(home, state)
    env = env_for(home, info, creds)
    pgdata = home/'postgres'
    passwordfile = home/'temp/pg-init-password'
    authconfig = home/'temp/redis-auth.conf'
    def start(name, command, child_env=env):
        record = native.spawn(home, 'logs/'+session+'/'+name, command, child_env)
        state['processes'][name] = record
        save(home, state)
        return record
    try:
        if not (pgdata/'PG_VERSION').exists():
            passwordfile.write_text(creds['pgadmin'], encoding='utf-8')
            with (logdir/'initdb.log').open('ab') as log:
                subprocess.run([str(Path(info['postgresBin'])/'initdb.exe'), '-D', str(pgdata),
                                '-U', 'zhiyi_admin', '--encoding=UTF8', '--locale=C',
                                '--auth=scram-sha-256', '--pwfile='+str(passwordfile)],
                               stdout=log, stderr=log, check=True)
            passwordfile.unlink()
            with (pgdata/'postgresql.conf').open('a', encoding='utf-8') as file:
                file.write("\nlisten_addresses='127.0.0.1'\nport=15432\npassword_encryption='scram-sha-256'\n")
        pg = start('postgres', [str(Path(info['postgresBin'])/'postgres.exe'), '-D', str(pgdata)])
        def postgres_ready():
            try: return sql(info, creds, 'SELECT 1;') == '1'
            except RuntimeError: return False
        desktop.wait_until(postgres_ready, pg, 60)
        if not info['initialized']:
            if not sql(info, creds, "SELECT 1 FROM pg_roles WHERE rolname='zhiyi_app';"):
                sql(info, creds, f"CREATE ROLE zhiyi_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD '{creds['db']}';")
            if not sql(info, creds, "SELECT 1 FROM pg_database WHERE datname='zhiyi';"):
                sql(info, creds, 'CREATE DATABASE zhiyi OWNER zhiyi_app;')
        # Configuration carries a DPAPI-decrypted password only during launch.
        # The stable non-secret settings are also recorded for support/backup.
        config = ('bind 127.0.0.1\nprotected-mode yes\nport 16379\n'
                  f'dir "{(home/"redis").as_posix()}"\n'
                  'appendonly yes\nappendfsync everysec\nsave 60 1\n'
                  'maxmemory-policy noeviction\n')
        (home/'redis/settings.conf').write_text(config, encoding='utf-8')
        authconfig.write_text(config+'requirepass '+creds['redis']+'\n', encoding='utf-8')
        redis = start('redis', [info['memurai'], str(authconfig)])
        client = redis_client(creds)
        desktop.wait_until(lambda: client.ping(), redis, 60)
        client.close()
        authconfig.unlink()
        schema(home, env, not (home/'data').exists())
        local_env = dict(env, PYTHONPATH=os.pathsep.join([str(ROOT/'apps/local-runtime'), str(ROOT/'apps/agentOS/src')]))
        start('host', [sys.executable, '-m', 'runtime.main'], local_env)
        ai = start('ai', [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host','127.0.0.1',
                           '--port','18761','--workers','1'])
        desktop.wait_until(lambda: native.health(18761,'/health/ready').get('status') == 'UP', ai, 180)
        java = start('java', [shutil.which('java'), '-jar', str(ROOT/'apps/backend/target/kinlin-backend-1.0.0.jar')],
                     java_environment(home, info, creds))
        desktop.wait_until(lambda: native.health(18080,'/actuator/health/readiness').get('status') == 'UP', java, 150)
        front_env = {key:value for key,value in env.items() if key in {
            'SYSTEMROOT','WINDIR','COMSPEC','PATH','PATHEXT','USERPROFILE','APPDATA','LOCALAPPDATA','PROGRAMDATA',
            'TEMP','TMP','NO_PROXY'}}
        front_env.update(DEV_BACKEND_PROXY_TARGET='http://127.0.0.1:18080', VITE_API_BASE_URL='')
        vite = start('frontend', [shutil.which('node'), str(ROOT/'apps/frontend/node_modules/vite/bin/vite.js'),
                                  str(ROOT/'apps/frontend'), '--mode','desktop','--host','127.0.0.1','--port','15200'], front_env)
        desktop.wait_until(lambda: native.health(15200,'/api/health/ready').get('status') == 'UP', vite, 60)
        if use_desktop:
            configfile = home/'tauri-native.json'
            native.write_json(configfile, {'identifier':'com.kinlin.zhiyi.native-dev',
                'build':{'beforeDevCommand':'','devUrl':'http://127.0.0.1:15200'}})
            appenv = dict(front_env, WEBVIEW2_USER_DATA_FOLDER=str(home/'webview'),
                          WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS='--remote-debugging-port=19222')
            for key in ['CARGO_HOME','RUSTUP_HOME','CARGO_TARGET_DIR','VSINSTALLDIR']:
                if os.getenv(key): appenv[key] = os.environ[key]
            record = desktop.spawn_app(home, 'logs/'+session+'/desktop', [shutil.which('node'),
                str(ROOT/'apps/desktop/node_modules/@tauri-apps/cli/tauri.js'), 'dev', '--config', str(configfile),
                '--no-watch','--','--bin','kinlin-native-dev'], appenv, ROOT/'apps/desktop')
            state['processes']['desktop'] = record
            save(home, state)
            desktop.wait_until(lambda: native.health(19222,'/json/version'), record, 240)
            state['desktopWindows'] = desktop.show_desktop(record)
            save(home, state)
        if not info['initialized']:
            info['initialized'] = True
            temporary = home/'environment.next.json'
            native.write_json(temporary, info)
            temporary.replace(home/'environment.json')
        result = status(home)
        native.write_json(logdir/'up.json', result)
        return result
    except BaseException:
        down(home)
        raise
    finally:
        passwordfile.unlink(missing_ok=True)
        authconfig.unlink(missing_ok=True)


def status(home):
    info, state = manifest(home), state_for(home)
    result = {'home':str(home), 'workspace':info['workspace'], 'services':{},
              'runtime':native.snapshot(state), 'redisLicense':info['redisLicense']}
    for name, record in state['processes'].items():
        result['services'][name] = {'alive':alive(record) is not None, 'process':record}
    try:
        creds = native.credentials(home)
        result['postgresReady'] = sql(info, creds, 'SELECT 1;') == '1'
        client = redis_client(creds)
        result['redisReady'] = client.ping()
        client.close()
        result['javaReady'] = native.health(18080,'/actuator/health/readiness')['status'] == 'UP'
    except Exception:
        result.update(postgresReady=False, redisReady=False, javaReady=False)
    result['status'] = 'UP' if result['services'] and all(x['alive'] for x in result['services'].values()) and result['runtime']['coreReady'] and all(result.get(x) for x in ['postgresReady','redisReady','javaReady']) else 'DOWN'
    return result


def down(home):
    info, state = manifest(home), state_for(home)
    creds = native.credentials(home)
    # Exact stale identities are never signalled; occupied ports still fail below.
    records = {name:record for name,record in state['processes'].items() if alive(record)}
    for name,record in reversed(list(records.items())):
        if name == 'desktop':
            desktop.close_desktop(record)
            native.stop(record)
        elif name == 'postgres':
            subprocess.run([str(Path(info['postgresBin'])/'pg_ctl.exe'), '-D', str(home/'postgres'),
                            'stop','-m','fast','-w','-t','45'], check=True, capture_output=True)
        elif name == 'redis':
            with redis_client(creds) as client: client.shutdown(save=True)
            parent = alive(record)
            if parent: parent.wait(20)
        else:
            native.stop(record)
    for port in PORTS if state.get('desktop') else PORTS[:-1]: native.port_free(port)
    cleaned = dict(state, processes=records)
    # This keeps the existing Windows workflow lock and exclusive-handle checks.
    cleanup = native.down(home, cleaned, preserve_credentials=True)
    result = {'status':'PASS','home':str(home),'cleanup':cleanup,'persistentCredentialsRetained':True}
    for name in ['pg-init-password','redis-auth.conf']:
        (home/'temp'/name).unlink(missing_ok=True)
    native.write_json(home/'logs/last-down.json', result)
    return result


def require_stopped(home):
    if any(alive(record) for record in state_for(home)['processes'].values()):
        raise RuntimeError('Stop the application before cold backup or restore')
    for port in PORTS: native.port_free(port)


def backup(home, destination):
    require_stopped(home)
    if not destination or not destination.is_absolute() or destination.exists() or destination.resolve().is_relative_to(home):
        raise RuntimeError('Snapshot must be a new absolute directory outside the persistent home')
    # Full cold cluster backup, same PostgreSQL major/binaries and same home path.
    # Keeping absolute content paths preserves the canonical Artifact contract.
    destination.mkdir(parents=True)
    protect(destination)
    payload = destination/'payload'
    excluded = {'logs','webview','temp','lifecycle.lock'}
    # Do not follow a workspace reparse point while creating a cold backup.
    for directory, directories, filenames in os.walk(home, followlinks=False):
        if Path(directory) == home:
            directories[:] = [name for name in directories if name not in excluded]
        for name in [*directories, *filenames]:
            candidate = Path(directory)/name
            if candidate.is_symlink() or candidate.is_junction():
                raise RuntimeError('Backup refuses reparse points')
    shutil.copytree(home, payload, symlinks=True,
                    ignore=lambda directory,names: set(names)&excluded if Path(directory)==home else set())
    files = {}
    for path in payload.rglob('*'):
        if path.is_symlink() or path.is_junction():
            raise RuntimeError('Backup refuses reparse points; use a separately managed workspace backup')
        if path.is_file(): files[str(path.relative_to(payload))] = hashlib.sha256(path.read_bytes()).hexdigest()
    result = {'format':FORMAT+'-cold-backup','home':str(home),'files':files,
              'credentials':'Current Windows user DPAPI; same user/machine required',
              'externalWorkspaceIncluded':False,'created':datetime.now(timezone.utc).isoformat()}
    native.write_json(destination/'snapshot.json', result)
    return {'status':'PASS','snapshot':str(destination),'files':len(files)}


def restore(home, source):
    require_stopped(home)
    if not source or not source.is_absolute(): raise RuntimeError('Absolute snapshot required')
    receipt = native.read_json(source/'snapshot.json')
    if receipt.get('format') != FORMAT+'-cold-backup' or receipt.get('home') != str(home):
        raise RuntimeError('Cold restore requires the original home path and PostgreSQL binary version')
    payload = source/'payload'
    for name,digest in receipt['files'].items():
        file = payload/name
        if not file.resolve().is_relative_to(payload.resolve()) or file.is_symlink() or file.is_junction():
            raise RuntimeError('Invalid snapshot path')
        if hashlib.sha256(file.read_bytes()).hexdigest() != digest: raise RuntimeError('Snapshot checksum mismatch')
    # Verify DPAPI before moving any current state. Keep the entire pre-restore
    # home as a sibling rollback copy; nothing is recursively deleted.
    native.credentials(payload)
    previous = home.with_name(home.name+'.pre-restore-'+secrets.token_hex(5))
    if previous.resolve().parent != home.resolve().parent or previous.exists():
        raise RuntimeError('Unsafe rollback directory')
    home.rename(previous)
    try:
        shutil.copytree(payload, home)
        for name in ['logs','temp','webview']: (home/name).mkdir(exist_ok=True)
        protect(home)
    except BaseException:
        raise RuntimeError('Restore interrupted; original home retained at '+str(previous))
    return {'status':'PASS','home':str(home),'rollbackCopy':str(previous),'snapshot':str(source)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init','up','status','down','recover','backup','restore'])
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--postgres-bin', type=Path)
    parser.add_argument('--memurai', type=Path)
    parser.add_argument('--provider-key-file', type=Path)
    parser.add_argument('--workspace', type=Path)
    parser.add_argument('--desktop', action='store_true')
    parser.add_argument('--snapshot', type=Path)
    args = parser.parse_args()
    home = args.home.absolute()
    validate_home(home)
    if not home.exists() and args.action in {'init','restore'}: home.mkdir(parents=True)
    if not home.is_dir(): raise RuntimeError('Initialize this persistent home first')
    control = home.with_name('.'+home.name+'-control')
    control.mkdir(exist_ok=True)
    with native.control_lock(control):
        if args.action == 'init': result = init(home,args)
        elif args.action == 'up': result = up(home,args.desktop)
        elif args.action == 'down': result = down(home)
        elif args.action == 'status': result = status(home)
        elif args.action == 'recover':
            down(home)
            result = up(home,args.desktop)
        elif args.action == 'backup': result = backup(home,args.snapshot)
        else: result = restore(home,args.snapshot)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return int(result['status'] == 'DOWN')


if __name__ == '__main__': raise SystemExit(main())
