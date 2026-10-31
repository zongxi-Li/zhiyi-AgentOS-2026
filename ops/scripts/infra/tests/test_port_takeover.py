"""端口接管：运行时启动前停掉占用者，再绑定知弈自己的服务。

不拉起真实进程；用假 owner/describe/stop 覆盖空闲、普通占用、启动器自身、
Windows 关键进程、不可检查进程与杀不掉六条路径，确保只有可核验的普通进程
会被停止，且绑定失败会在停止后再次确认。
"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'windows' / 'native'))
import native_runtime as native  # noqa: E402


def record(pid=4242, executable='C:/tools/node.exe', command=('node', 'vite.js')):
    return {'pid': pid, 'created': 1.0, 'executable': executable, 'command': list(command)}


def busy_once(monkeypatch):
    """port_free fails on first call (occupied) and succeeds afterwards (released)."""
    calls = []

    def port_free(port):
        calls.append(port)
        if len(calls) == 1:
            raise OSError(10048, 'address already in use')

    monkeypatch.setattr(native, 'port_free', port_free)
    return calls


def test_free_port_is_left_alone(monkeypatch):
    monkeypatch.setattr(native, 'port_free', Mock())
    owners = Mock(return_value=[])
    monkeypatch.setattr(native, 'port_owners', owners)
    assert native.release_port(15999) is None
    owners.assert_not_called()


def test_busy_port_stops_its_owner_before_binding(monkeypatch):
    calls = busy_once(monkeypatch)
    monkeypatch.setattr(native, 'port_owners', lambda port: [4242])
    monkeypatch.setattr(native, '_parents', lambda: [])
    process = record()
    monkeypatch.setattr(native, 'describe', lambda pid: process)
    stop = Mock(return_value='terminated')
    monkeypatch.setattr(native, 'stop_external', stop)

    released = native.release_port(15200)

    stop.assert_called_once_with(process)
    assert released == [{'port': 15200, 'pid': 4242, 'process': process, 'outcome': 'terminated'}]
    assert calls == [15200, 15200]  # probed, stopped, then verified bindable


def test_launcher_never_stops_itself(monkeypatch):
    busy_once(monkeypatch)
    monkeypatch.setattr(native, 'port_owners', lambda port: [os.getpid()])
    monkeypatch.setattr(native, '_parents', lambda: [])
    stop = Mock()
    monkeypatch.setattr(native, 'stop_external', stop)
    with pytest.raises(RuntimeError, match='launcher itself'):
        native.release_port(18080)
    stop.assert_not_called()


def test_launcher_never_stops_its_ancestors(monkeypatch):
    busy_once(monkeypatch)
    monkeypatch.setattr(native, 'port_owners', lambda port: [777])
    monkeypatch.setattr(native, '_parents', lambda: [SimpleNamespace(pid=777)])
    with pytest.raises(RuntimeError, match='launcher itself'):
        native.release_port(18080)


def test_protected_windows_process_is_refused(monkeypatch):
    busy_once(monkeypatch)
    monkeypatch.setattr(native, 'port_owners', lambda port: [612])
    monkeypatch.setattr(native, '_parents', lambda: [])
    monkeypatch.setattr(native, 'describe', lambda pid: record(pid, 'C:/Windows/System32/svchost.exe'))
    stop = Mock()
    monkeypatch.setattr(native, 'stop_external', stop)
    with pytest.raises(RuntimeError, match='Windows process svchost.exe'):
        native.release_port(15432)
    stop.assert_not_called()


def test_uninspectable_owner_is_refused(monkeypatch):
    busy_once(monkeypatch)
    monkeypatch.setattr(native, 'port_owners', lambda port: [9001])
    monkeypatch.setattr(native, '_parents', lambda: [])
    monkeypatch.setattr(native, 'describe', lambda pid: None)
    with pytest.raises(RuntimeError, match='cannot inspect'):
        native.release_port(16379)


def test_unidentified_owner_is_refused(monkeypatch):
    busy_once(monkeypatch)
    monkeypatch.setattr(native, 'port_owners', lambda port: [])
    with pytest.raises(RuntimeError, match='owner could not be identified'):
        native.release_port(15200)


def test_port_must_be_bindable_after_stopping(monkeypatch):
    def never_free(port):
        raise OSError(10048, 'address already in use')

    monkeypatch.setattr(native, 'port_free', never_free)
    monkeypatch.setattr(native, 'port_owners', lambda port: [4242])
    monkeypatch.setattr(native, '_parents', lambda: [])
    monkeypatch.setattr(native, 'describe', lambda pid: record(pid))
    monkeypatch.setattr(native, 'stop_external', Mock(return_value='killed'))
    with pytest.raises(RuntimeError, match='still in use'):
        native.release_port(19222)


def test_release_ports_covers_every_target_port(monkeypatch):
    seen = []

    def release_port(port):
        seen.append(port)
        return [{'port': port, 'pid': port}] if port == 15200 else None

    monkeypatch.setattr(native, 'release_port', release_port)
    released = native.release_ports([15200, 18080])
    assert seen == [15200, 18080]
    assert released == [{'port': 15200, 'pid': 15200}]

def test_takeover_is_recorded_without_command_lines(tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'windows' / 'native'))
    import persistent_runtime as runtime

    written = {}
    monkeypatch.setattr(runtime.native, 'write_json', lambda path, value: written.update(path=path, value=value))
    released = [{'port': 15200, 'pid': 99, 'outcome': 'graceful',
                 'process': {'executable': 'C:/tools/node.exe', 'command': ['node', '--token=secret']}}]
    runtime.record_port_takeover(tmp_path, released)

    assert written['path'] == tmp_path / 'port-takeover.json'
    assert written['value']['released'] == [
        {'port': 15200, 'pid': 99, 'executable': 'C:/tools/node.exe', 'outcome': 'graceful'}]
