"""Shared desktop-window lifecycle helpers for the native Windows runtimes.

N02（Docker relay 桌面开发入口）已退役：Docker 转发、isolated database
provisioning 与 N02 自身的 up/status/down 入口全部删除，桌面运行形态只剩
N03（`persistent_runtime.py`）与桌面热更新链（`ops/scripts/start-desktop-hot.ps1`）。

本模块只保留两条链共用的「拉起桌面壳 / 给窗口焦点 / 关闭窗口 / 等就绪」
助手；进程身份校验、端口检查、数据库与凭据仍由各自 runtime 与
`native_runtime.py` 负责，这里不引入任何 Docker、数据库或 relay 逻辑。
"""
import subprocess
import time

import native_runtime as native
import desktop_shell


def spawn_app(run, name, command, env, cwd):
    """Spawn the desktop shell and return its verified process identity."""
    import psutil
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = subprocess.SW_HIDE
    with (run / f'{name}.log').open('ab') as log:
        child = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=log,
                                 creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=info)
    return native.identity(psutil.Process(child.pid))


def show_desktop(record, classes=desktop_shell.ELECTRON_WINDOW_CLASSES):
    """The interactive app window is visible; its helper console stays hidden."""
    import win32con
    import win32gui
    import win32process
    parent = native.owned(record)
    if parent is None:
        return []
    pids = {p.pid for p in [parent, *parent.children(recursive=True)]}
    windows = []

    def visit(hwnd, _context):
        _thread, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid in pids and win32gui.GetClassName(hwnd) in classes:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            try:
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass
            windows.append({'pid': pid, 'handle': hwnd, 'visible': bool(win32gui.IsWindowVisible(hwnd))})

    win32gui.EnumWindows(visit, None)
    return windows


def close_desktop(record, classes=desktop_shell.ELECTRON_WINDOW_CLASSES):
    """Close only windows descended from this lifecycle's verified owner."""
    import win32con
    import win32gui
    import win32process
    parent = native.owned(record)
    if parent is None:
        return
    pids = {p.pid for p in [parent, *parent.children(recursive=True)]}

    def visit(hwnd, _context):
        _thread, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid in pids and win32gui.GetClassName(hwnd) in classes:
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)

    win32gui.EnumWindows(visit, None)
    deadline = time.monotonic() + 12
    while native.owned(record) and time.monotonic() < deadline:
        time.sleep(.2)


def wait_until(check, process, timeout=90):
    """Poll `check`; fail fast (with the owned PID) if the process exits."""
    import redis
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if native.owned(process) is None:
            raise RuntimeError(f'Owned process {process["pid"]} exited; inspect its session log')
        try:
            result = check()
            if result:
                return result
        except (OSError, ValueError, redis.exceptions.ConnectionError):
            pass
        time.sleep(.5)
    raise RuntimeError(f'Service readiness timed out after {timeout}s (owned PID {process["pid"]})')
