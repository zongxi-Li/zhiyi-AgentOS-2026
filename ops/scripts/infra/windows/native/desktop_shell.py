"""Desktop Shell 启动适配：Tauri 与 Electron 共用同一原生生命周期边界。

N02/N03 的进程身份校验（native.identity/owned）、端口检查、健康等待与
停止语义保持不变；本模块只把「拉起桌面壳并识别其窗口」这一步抽象为两种
实现，避免两个 runtime 各自内联 Tauri 专属细节：

- tauri（默认，保留作回归与故障回退）：tauri.js dev + WebView2 调试端口
  19222 + 窗口类名 'Tauri Window'；
- electron：node electron/cli.js 指向既有 Vite dev server + Chromium
  --remote-debugging-port=19222（就绪探测同为 /json/version）+ 窗口类名
  'Chrome_WidgetWin_1'。

选择经 KINLIN_DESKTOP_SHELL 环境变量（'tauri'|'electron'），默认 tauri；
两种壳都不承载任务执行——执行权威仍在 Runtime/Host 进程。
"""
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]

SHELLS = ('tauri', 'electron')
REMOTE_DEBUG_PORT = 19222
TAURI_WINDOW_CLASS = 'Tauri Window'
ELECTRON_WINDOW_CLASSES = ('Chrome_WidgetWin_1',)

FRONTEND_MODES = {'tauri': 'desktop', 'electron': 'electron'}


def current_shell(environ=None):
    """读取并校验 shell 选择；未设置或空值回退 tauri，非法值立即失败。"""
    raw = (environ if environ is not None else os.environ).get('KINLIN_DESKTOP_SHELL') or 'tauri'
    shell = raw.strip().lower()
    if shell not in SHELLS:
        raise RuntimeError(f'Unknown desktop shell {shell!r}; expected one of {SHELLS}')
    return shell


def frontend_mode(shell):
    """桌面壳对应的 Vite 构建模式（平台适配层经 @platform 别名切换）。"""
    if shell not in SHELLS:
        raise RuntimeError(f'Unknown desktop shell {shell!r}')
    return FRONTEND_MODES[shell]


def window_classes(shell):
    """EnumWindows 匹配用的顶层窗口类名。"""
    if shell == 'tauri':
        return (TAURI_WINDOW_CLASS,)
    if shell == 'electron':
        return ELECTRON_WINDOW_CLASSES
    raise RuntimeError(f'Unknown desktop shell {shell!r}')


def desktop_command(root, shell, dev_server_url, config_path=None,
                    debug_port=REMOTE_DEBUG_PORT, bin_name=None):
    """构造桌面壳启动命令；返回 (command, cwd)。

    tauri 需要调用方先写好 --config（identifier/devUrl 与运行目录绑定），
    bin_name 可覆盖默认的 kinlin-native-dev（端口偏移环境用 kinlin-integration-dev）；
    electron 直接把 dev server URL 与调试端口作为应用参数传入。
    """
    node = shutil.which('node')
    if not node:
        raise RuntimeError('node not found in PATH')
    if shell == 'tauri':
        if config_path is None:
            raise RuntimeError('The tauri shell requires a generated config file')
        cli = root / 'apps/desktop/node_modules/@tauri-apps/cli/tauri.js'
        if not cli.is_file():
            raise RuntimeError('Missing Tauri CLI; run npm install in apps/desktop')
        command = [node, str(cli), 'dev', '--config', str(config_path),
                   '--no-watch', '--', '--bin', bin_name or 'kinlin-native-dev']
        return command, root / 'apps/desktop'
    if shell == 'electron':
        cli = root / 'apps/desktop/electron/node_modules/electron/cli.js'
        if not cli.is_file():
            raise RuntimeError('Missing Electron runtime; run npm install in apps/desktop/electron')
        command = [node, str(cli), str(root / 'apps/desktop/electron'),
                   f'--dev-server={dev_server_url}',
                   f'--remote-debugging-port={debug_port}']
        return command, root / 'apps/desktop/electron'
    raise RuntimeError(f'Unknown desktop shell {shell!r}')


def desktop_env(shell, front_env, run_dir, debug_port=REMOTE_DEBUG_PORT):
    """在受限前端环境之上补桌面壳专属变量。"""
    env = dict(front_env)
    if shell == 'tauri':
        env['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = f'--remote-debugging-port={debug_port}'
        env['WEBVIEW2_USER_DATA_FOLDER'] = str(run_dir / 'webview')
        for key in ['CARGO_HOME', 'RUSTUP_HOME', 'CARGO_TARGET_DIR', 'VSINSTALLDIR']:
            if os.getenv(key):
                env[key] = os.environ[key]
    elif shell != 'electron':
        raise RuntimeError(f'Unknown desktop shell {shell!r}')
    return env


def ready_check(debug_port=REMOTE_DEBUG_PORT):
    """两种壳的就绪探测完全一致：Chromium 系 CDP /json/version。"""
    import native_runtime as native
    return lambda: native.health(debug_port, '/json/version')
