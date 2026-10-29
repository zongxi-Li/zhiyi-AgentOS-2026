"""native_runtime.stop 的停机语义：先优雅、超时才按已验证进程树终止。

不拉起真实进程；用假 psutil 进程覆盖 graceful / terminate / kill / 拒绝终止
四条路径，确保任何强杀只发生在 native.owned() 已核验身份的进程树上，且升级
动作会以 WARNING 写 stderr 并作为 'terminated'/'killed' 回执返回。
"""
import subprocess
import sys
import unittest.mock as mock
from pathlib import Path

import pytest

NATIVE_DIR = Path(__file__).resolve().parents[1] / 'windows' / 'native'
sys.path.insert(0, str(NATIVE_DIR))

import native_runtime as native  # noqa: E402


class FakeProcess:
    def __init__(self, pid=4242, waits=(), children=()):
        self.pid = pid
        self._waits = list(waits)
        self._children = list(children)
        self.terminated = False
        self.killed = False

    def children(self, recursive=True):
        return list(self._children)

    def wait(self, timeout=None):
        action = self._waits.pop(0) if self._waits else 0
        if action == 'timeout':
            raise subprocess.TimeoutExpired('fake', timeout)
        return action

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


def run_stop(monkeypatch, process, **kwargs):
    monkeypatch.setattr(native, 'owned', lambda record: process)
    monkeypatch.setattr(native.subprocess, 'run', mock.Mock())
    return native.stop({'pid': process.pid}, **kwargs)


def test_stop_returns_none_when_process_already_gone(monkeypatch):
    monkeypatch.setattr(native, 'owned', lambda record: None)
    assert native.stop({'pid': 1}) is None


def test_graceful_stop_never_terminates(monkeypatch):
    child = FakeProcess(pid=2, waits=[0])
    parent = FakeProcess(waits=[0], children=[child])
    assert run_stop(monkeypatch, parent) == 'graceful'
    assert parent.terminated is False
    assert child.terminated is False


def test_graceful_timeout_escalates_to_verified_tree_terminate(monkeypatch, capsys):
    child = FakeProcess(pid=2, waits=[0])
    parent = FakeProcess(waits=['timeout', 'timeout', 0], children=[child])
    assert run_stop(monkeypatch, parent) == 'terminated'
    assert parent.terminated is True and parent.killed is False
    assert child.terminated is True
    assert 'terminating the verified tree' in capsys.readouterr().err


def test_terminate_timeout_falls_back_to_kill(monkeypatch):
    parent = FakeProcess(waits=['timeout', 'timeout', 'timeout', 0])
    assert run_stop(monkeypatch, parent) == 'killed'
    assert parent.killed is True


def test_allow_terminate_false_keeps_evidence(monkeypatch):
    parent = FakeProcess(waits=['timeout', 'timeout'])
    with pytest.raises(RuntimeError, match='Graceful stop failed'):
        run_stop(monkeypatch, parent, allow_terminate=False)
    assert parent.terminated is False
