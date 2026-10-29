"""Desktop Shell 启动适配（Tauri/Electron）的纯逻辑单测。

不拉起进程、不碰端口；命令构造与 env 组装在假目录树上验证。
"""
import sys
import unittest.mock as mock
from pathlib import Path

import pytest

NATIVE_DIR = Path(__file__).resolve().parents[1] / 'windows' / 'native'
sys.path.insert(0, str(NATIVE_DIR))

import desktop_shell  # noqa: E402


def make_fake_root(tmp_path, shell):
    """构造带桌面壳 CLI 占位文件的假仓库根目录。"""
    root = tmp_path / 'repo'
    if shell == 'tauri':
        cli = root / 'apps/desktop/node_modules/@tauri-apps/cli/tauri.js'
    else:
        cli = root / 'apps/desktop/electron/node_modules/electron/cli.js'
    cli.parent.mkdir(parents=True)
    cli.write_text('// placeholder\n', encoding='utf-8')
    return root


class TestShellSelection:
    def test_default_is_tauri_for_rollback_safety(self):
        assert desktop_shell.current_shell({}) == 'tauri'
        assert desktop_shell.current_shell({'KINLIN_DESKTOP_SHELL': ''}) == 'tauri'

    def test_electron_selected_and_normalized(self):
        assert desktop_shell.current_shell({'KINLIN_DESKTOP_SHELL': 'electron'}) == 'electron'
        assert desktop_shell.current_shell({'KINLIN_DESKTOP_SHELL': ' Electron '}) == 'electron'

    def test_unknown_shell_fails_loudly(self):
        with pytest.raises(RuntimeError):
            desktop_shell.current_shell({'KINLIN_DESKTOP_SHELL': 'webview2'})

    def test_frontend_mode_and_window_classes(self):
        assert desktop_shell.frontend_mode('tauri') == 'desktop'
        assert desktop_shell.frontend_mode('electron') == 'electron'
        assert desktop_shell.window_classes('tauri') == ('Tauri Window',)
        assert 'Chrome_WidgetWin_1' in desktop_shell.window_classes('electron')
        with pytest.raises(RuntimeError):
            desktop_shell.frontend_mode('unknown')


class TestDesktopCommand:
    def test_tauri_command_shape(self, tmp_path):
        root = make_fake_root(tmp_path, 'tauri')
        config = tmp_path / 'tauri-native.json'
        with mock.patch.object(desktop_shell.shutil, 'which', return_value='node.exe'):
            command, cwd = desktop_shell.desktop_command(root, 'tauri', 'http://127.0.0.1:15200', config_path=config)
        assert command[:3] == ['node.exe', str(root / 'apps/desktop/node_modules/@tauri-apps/cli/tauri.js'), 'dev']
        assert command[command.index('--config') + 1] == str(config)
        assert command[command.index('--bin') + 1] == 'kinlin-native-dev'
        assert cwd == root / 'apps/desktop'

    def test_tauri_requires_config(self, tmp_path):
        root = make_fake_root(tmp_path, 'tauri')
        with pytest.raises(RuntimeError):
            desktop_shell.desktop_command(root, 'tauri', 'http://127.0.0.1:15200')

    def test_electron_command_shape(self, tmp_path):
        root = make_fake_root(tmp_path, 'electron')
        with mock.patch.object(desktop_shell.shutil, 'which', return_value='node.exe'):
            command, cwd = desktop_shell.desktop_command(root, 'electron', 'http://127.0.0.1:15200')
        assert command[1] == str(root / 'apps/desktop/electron/node_modules/electron/cli.js')
        assert '--dev-server=http://127.0.0.1:15200' in command
        assert '--remote-debugging-port=19222' in command
        assert cwd == root / 'apps/desktop/electron'

    def test_port_offset_environments_override_debug_port_and_bin(self, tmp_path):
        root = make_fake_root(tmp_path, 'tauri')
        electron_cli = root / 'apps/desktop/electron/node_modules/electron/cli.js'
        electron_cli.parent.mkdir(parents=True)
        electron_cli.write_text('// placeholder\n', encoding='utf-8')
        config = tmp_path / 'tauri-native.json'
        with mock.patch.object(desktop_shell.shutil, 'which', return_value='node.exe'):
            command, _ = desktop_shell.desktop_command(root, 'tauri', 'http://127.0.0.1:15210',
                                                       config_path=config, debug_port=19223,
                                                       bin_name='kinlin-integration-dev')
            electron, _ = desktop_shell.desktop_command(root, 'electron', 'http://127.0.0.1:15210',
                                                        debug_port=19223)
        assert command[command.index('--bin') + 1] == 'kinlin-integration-dev'
        assert '--remote-debugging-port=19223' in electron

    def test_tauri_env_debug_port_follows_offset(self, tmp_path):
        env = desktop_shell.desktop_env('tauri', {'PATH': 'p'}, tmp_path, debug_port=19223)
        assert env['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] == '--remote-debugging-port=19223'

    def test_missing_runtime_fails_with_install_hint(self, tmp_path):
        root = tmp_path / 'repo'
        with mock.patch.object(desktop_shell.shutil, 'which', return_value='node.exe'):
            with pytest.raises(RuntimeError, match='apps/desktop/electron'):
                desktop_shell.desktop_command(root, 'electron', 'http://127.0.0.1:15200')
            with pytest.raises(RuntimeError, match='apps/desktop'):
                desktop_shell.desktop_command(root, 'tauri', 'http://127.0.0.1:15200', config_path=root / 'c.json')

    def test_missing_node_fails(self, tmp_path):
        root = make_fake_root(tmp_path, 'electron')
        with mock.patch.object(desktop_shell.shutil, 'which', return_value=None):
            with pytest.raises(RuntimeError, match='node'):
                desktop_shell.desktop_command(root, 'electron', 'http://127.0.0.1:15200')


class TestDesktopEnv:
    BASE = {'PATH': 'C:/windows', 'SYSTEMROOT': 'C:/windows'}

    def test_tauri_env_adds_webview2_and_cargo(self, tmp_path):
        with mock.patch.dict(desktop_shell.os.environ, {'CARGO_HOME': 'F:/cargo'}, clear=True):
            env = desktop_shell.desktop_env('tauri', self.BASE, tmp_path)
        assert env['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] == '--remote-debugging-port=19222'
        assert env['WEBVIEW2_USER_DATA_FOLDER'] == str(tmp_path / 'webview')
        assert env['CARGO_HOME'] == 'F:/cargo'
        assert env['PATH'] == 'C:/windows'

    def test_electron_env_is_restricted_copy(self, tmp_path):
        env = desktop_shell.desktop_env('electron', self.BASE, tmp_path)
        assert env == self.BASE
        assert 'WEBVIEW2_USER_DATA_FOLDER' not in env
        assert 'CARGO_HOME' not in env

    def test_unknown_shell_rejected(self, tmp_path):
        with pytest.raises(RuntimeError):
            desktop_shell.desktop_env('webview2', self.BASE, tmp_path)


class TestRuntimeWiring:
    """两个 runtime 对 desktop_shell 的接线：导入即验证签名兼容。"""

    def test_desktop_runtime_exposes_shell_aware_window_helpers(self):
        import desktop_runtime
        assert desktop_runtime.show_desktop.__defaults__ == (('Tauri Window',),)
        assert desktop_runtime.close_desktop.__defaults__ == (('Tauri Window',),)

    def test_persistent_runtime_defaults_cors_to_include_electron_origin(self):
        import persistent_runtime
        source = (NATIVE_DIR / 'persistent_runtime.py').read_text(encoding='utf-8')
        creds = {'token': 't', 'key': 'k', 'hmac': 'h', 'deepseek': 'd',
                 'db': 'db', 'redis': 'r', 'jwt': 'j'}
        origins = persistent_runtime.java_environment(
            Path('C:/home'), {'workspace': 'C:/home/workspace'}, creds)['CORS_ALLOWED_ORIGINS']
        assert 'kinlin-app://shell' in origins
        assert 'http://127.0.0.1:15200' in origins
        assert 'desktop_shell.window_classes' in source

    def test_persistent_runtime_cors_and_debug_port_follow_port_offset(self):
        import persistent_runtime
        creds = {'token': 't', 'key': 'k', 'hmac': 'h', 'deepseek': 'd',
                 'db': 'db', 'redis': 'r', 'jwt': 'j'}
        info = {'workspace': 'C:/home/workspace', 'portOffset': 10}
        origins = persistent_runtime.java_environment(Path('C:/home'), info, creds)['CORS_ALLOWED_ORIGINS']
        assert 'http://127.0.0.1:15210' in origins
        assert 'http://127.0.0.1:15200' not in origins
        assert persistent_runtime.ports(info)['debug'] == 19232


def test_ready_check_returns_callable():
    probe = desktop_shell.ready_check()
    assert callable(probe)


def test_ready_check_uses_offset_debug_port():
    import native_runtime as native
    with mock.patch.object(native, 'health', return_value={'ok': True}) as health:
        probe = desktop_shell.ready_check(19223)
        assert probe()
    health.assert_called_once_with(19223, '/json/version')
