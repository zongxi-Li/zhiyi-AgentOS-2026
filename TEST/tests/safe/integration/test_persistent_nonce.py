"""持久nonce的独立进程争用、应用重启和认证故障隔离。

仅使用合成凭据与测试runner，不计为真实模型、网络或DP验收。
"""

import json
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import threading
import time

import pytest


WORKER = r'''
import json, os, pathlib, sys, time
sys.path.insert(0, sys.argv[1])
from components.safe.infrastructure.storage.sqlite_nonces import SqliteNonceStore
path, ready, go, nonce, credential, total, per_owner = sys.argv[2:]
try:
    store = SqliteNonceStore(pathlib.Path(path), clock=lambda: 100.0,
        max_entries=int(total), max_per_credential=int(per_owner), timeout=3.0)
    pathlib.Path(ready).touch()
    deadline = time.monotonic() + 30
    while not pathlib.Path(go).exists():
        if time.monotonic() > deadline:
            raise TimeoutError()
        time.sleep(0.01)
    accepted = store.consume(credential, nonce, 160.0)
    print(json.dumps({"accepted": accepted}), flush=True)
except Exception as exc:
    print(json.dumps({"failure_type": type(exc).__name__}), flush=True)
    raise SystemExit(1)
'''


@pytest.mark.parametrize("mode,expected", [("same-nonce", 1), ("total-capacity", 2), ("credential-capacity", 1)])
def test_separate_processes_atomically_share_nonce_and_capacity(tmp_path, mode, expected):
    from components.safe.infrastructure.storage.sqlite_nonces import SqliteNonceStore

    total, per_credential = (2, 4) if mode == "total-capacity" else (10, 1 if mode == "credential-capacity" else 4)
    path = tmp_path / "replay.db"
    SqliteNonceStore.create(path, clock=lambda: 100.0, max_entries=total, max_per_credential=per_credential)
    source = Path(__file__).resolve().parents[4] / "apps/agentOS/src"
    go = tmp_path / "go"
    children = []
    try:
        for index in range(4):
            ready = tmp_path / f"ready-{index}"
            nonce = "a" * 32 if mode == "same-nonce" else f"{index:032x}"
            credential = f"credential-{index}" if mode == "total-capacity" else "credential-a"
            child = subprocess.Popen([sys.executable, "-B", "-c", WORKER, str(source), str(path), str(ready),
                str(go), nonce, credential, str(total), str(per_credential)],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            children.append((child, ready))
        deadline = time.monotonic() + 30
        while not all(ready.exists() for _, ready in children):
            if any(child.poll() is not None for child, _ in children) or time.monotonic() > deadline:
                pytest.fail("独立进程未在限定时间内就绪")
            time.sleep(0.01)
        go.touch()
        results = []
        for child, _ in children:
            output, _ = child.communicate(timeout=30)
            assert child.returncode == 0, output
            results.append(json.loads(output)["accepted"])
        assert sum(results) == expected
        # 父进程也必须看见已提交状态，不能只在子进程局部去重。
        reopened = SqliteNonceStore(path, clock=lambda: 100.0, max_entries=total, max_per_credential=per_credential)
        if mode == "same-nonce":
            assert not reopened.consume("credential-a", "a" * 32, 160.0)
        with sqlite3.connect(path) as connection:
            objects = connection.execute("SELECT name, sql FROM sqlite_master WHERE type='table'").fetchall()
        assert objects  # 表结构明细由适配器单元测试核验。
    finally:
        go.touch()
        for child, _ in children:
            if child.poll() is None:
                child.terminate()
            child.communicate(timeout=10)


def test_committed_nonce_survives_worker_exit_and_second_process(tmp_path):
    from components.safe.infrastructure.storage.sqlite_nonces import SqliteNonceStore

    path = tmp_path / "restart.db"
    SqliteNonceStore.create(path, clock=lambda: 100.0)
    source = Path(__file__).resolve().parents[4] / "apps/agentOS/src"
    code = """
import os,pathlib,sys
sys.path.insert(0,sys.argv[1])
from components.safe.infrastructure.storage.sqlite_nonces import SqliteNonceStore
s=SqliteNonceStore(pathlib.Path(sys.argv[2]),clock=lambda:100.0)
accepted=s.consume('credential-a','a'*32,160.0)
os._exit(0 if accepted else 3)
"""
    options = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    first = subprocess.run([sys.executable, "-B", "-c", code, str(source), str(path)], **options)
    second = subprocess.run([sys.executable, "-B", "-c", code, str(source), str(path)], **options)
    assert first.returncode == 0 and second.returncode == 3


@pytest.mark.parametrize("failure", ["locked", "deleted", "corrupt"])
def test_http_nonce_failure_is_fixed_authentication_failure_before_kv(tmp_path, failure):
    pytest.importorskip("httpx")
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from components.safe.infrastructure.storage.sqlite_nonces import SqliteNonceStore
    from components.safe.infrastructure.security.signing import sign_request
    from test_http_bootstrap import make_app, make_credential

    path = tmp_path / "private-state.db"
    store = SqliteNonceStore.create(path, timeout=0.05)
    app, runner, _, digest = make_app(nonce_store=store)
    body = json.dumps({"manifest_digest": digest}).encode()
    route = "/safe/v1/sessions"
    headers = {**sign_request(credential=make_credential(), method="POST", path=route,
        timestamp=int(time.time()), nonce=secrets.token_hex(16), body=body), "Content-Type": "application/json"}
    lock = None
    try:
        if failure == "locked":
            lock = sqlite3.connect(path, isolation_level=None)
            lock.execute("BEGIN IMMEDIATE")
        elif failure == "deleted":
            path.unlink()
        else:
            path.write_bytes(b"SYNTHETIC_PRIVATE_STATE_CORRUPTED")
        with TestClient(app, base_url="https://testserver") as client:
            result = client.post(route, content=body, headers=headers)
            assert result.status_code == 401
            assert result.json() == {"code": "AUTHENTICATION_FAILED"}
            assert not runner.handles and not runner.forward_handles
    finally:
        if lock is not None:
            lock.rollback()
            lock.close()
    if failure == "deleted":
        assert not path.exists()


def test_http_replay_is_rejected_after_application_and_store_restart(tmp_path):
    pytest.importorskip("httpx")
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from components.safe.infrastructure.storage.sqlite_nonces import SqliteNonceStore
    from components.safe.infrastructure.security.signing import sign_request
    from test_http_bootstrap import make_app, make_credential

    path = tmp_path / "restart.db"
    SqliteNonceStore.create(path)
    route, body = "/safe/v1/sessions", None
    previous_headers = None
    for index in range(2):
        app, runner, _, digest = make_app(nonce_store=SqliteNonceStore(path))
        body = json.dumps({"manifest_digest": digest}).encode()
        headers = {**sign_request(credential=make_credential(), method="POST", path=route,
            timestamp=int(time.time()), nonce=secrets.token_hex(16), body=body), "Content-Type": "application/json"}
        with TestClient(app, base_url="https://testserver") as client:
            if index:
                response = client.post(route, content=body, headers=previous_headers)
                assert response.status_code == 401
                assert not runner.handles
            assert client.post(route, content=body, headers=headers).status_code == 200
            assert runner.handles
        assert not runner.handles
        previous_headers = headers


def test_two_live_http_apps_share_atomic_replay_decision(tmp_path):
    pytest.importorskip("httpx")
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from components.safe.infrastructure.storage.sqlite_nonces import SqliteNonceStore
    from components.safe.infrastructure.security.signing import sign_request
    from test_http_bootstrap import make_app, make_credential

    path = tmp_path / "shared.db"
    SqliteNonceStore.create(path)
    first, runner_a, _, digest = make_app(nonce_store=SqliteNonceStore(path, timeout=3.0))
    second, runner_b, _, _ = make_app(nonce_store=SqliteNonceStore(path, timeout=3.0))
    route = "/safe/v1/sessions"
    body = json.dumps({"manifest_digest": digest}).encode()
    signed = {**sign_request(credential=make_credential(), method="POST", path=route,
        timestamp=int(time.time()), nonce=secrets.token_hex(16), body=body), "Content-Type": "application/json"}
    barrier = threading.Barrier(2)

    def create(client):
        barrier.wait(timeout=10)
        return client.post(route, content=body, headers=signed).status_code

    with TestClient(first, base_url="https://testserver") as client_a, TestClient(second, base_url="https://testserver") as client_b:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, (client_a, client_b)))
        assert sorted(results) == [200, 401]
        assert len(runner_a.handles) + len(runner_b.handles) == 1
    assert not runner_a.handles and not runner_b.handles
