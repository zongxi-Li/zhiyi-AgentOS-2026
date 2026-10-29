"""Desktop Shell 启动适配：Electron 单壳，沿用既有原生生命周期边界。

N02/N03 的进程身份校验（native.identity/owned）、端口检查、健康等待与
停止语义保持不变；本模块只把「拉起桌面壳并识别其窗口」这一步收敛为
Electron 唯一实现。Tauri 壳已随桌面入口切换整体移除（迁移与验收过程见
docs/开发记录/PR-EL-01 系列报告）：

- electron：node electron/cli.js 指向既有 Vite dev server + Chromium
  --remote-debugging-port=19222（就绪探测 /json/version）+ 窗口类名
  'Chrome_WidgetWin_1'；端口偏移环境经 debug_port 使用 19222+PortOffset，
  不再需要专用开发二进制。

选择经 KINLIN_DESKTOP_SHELL 环境变量（仅接受 'electron'，未设置等同），
其他值立即失败；壳不承载任务执行——执行权威仍在 Runtime/Host 进程。
"""
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]

SHELLS = ('electron',)
REMOTE_DEBUG_PORT = 19222
ELECTRON_WINDOW_CLASSES = ('Chrome_WidgetWin_1',)

FRONTEND_MODES = {'electron': 'electron'}


def current_shell(environ=None):
    """读取并校验 shell 选择；未设置或空值即 electron，非法值立即失败。"""
    raw = (environ if environ is not None else os.environ).get('KINLIN_DESKTOP_SHELL') or 'electron'
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
    if shell == 'electron':
        return ELECTRON_WINDOW_CLASSES
    raise RuntimeError(f'Unknown desktop shell {shell!r}')


def desktop_command(root, shell, dev_server_url, debug_port=REMOTE_DEBUG_PORT):
    """构造桌面壳启动命令；返回 (command, cwd)。

    electron 直接把 dev server URL 与调试端口作为应用参数传入。
    """
    node = shutil.which('node')
    if not node:
        raise RuntimeError('node not found in PATH')
    if shell == 'electron':
        cli = root / 'apps/desktop/electron/node_modules/electron/cli.js'
        if not cli.is_file():
            raise RuntimeError('Missing Electron runtime; run npm install in apps/desktop/electron')
        command = [node, str(cli), str(root / 'apps/desktop/electron'),
                   f'--dev-server={dev_server_url}',
                   f'--remote-debugging-port={debug_port}']
        return command, root / 'apps/desktop/electron'
    raise RuntimeError(f'Unknown desktop shell {shell!r}')


def desktop_env(shell, front_env):
    """Electron 壳只继承受限前端环境副本，不注入任何 WebView/Cargo 变量。"""
    if shell != 'electron':
        raise RuntimeError(f'Unknown desktop shell {shell!r}')
    return dict(front_env)


def ready_check(debug_port=REMOTE_DEBUG_PORT):
    """就绪探测：Chromium 系 CDP /json/version。"""
    import native_runtime as native
    return lambda: native.health(debug_port, '/json/version')
