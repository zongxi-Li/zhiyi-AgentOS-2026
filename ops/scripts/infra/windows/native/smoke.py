"""Real Windows production composition -> LocalRuntimeClient -> HMAC HTTP.

Runs in a separate native Python process using its own explicitly prepared
SQLite stores. The concurrently running FastAPI service is checked separately;
this does not add a test execution endpoint to the production API.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent))
from native_runtime import credentials, environment, inspect_symlink, owned, read_json, snapshot, spawn, stop, write_json


async def exercise(run, invocation_id):
    # Import the real application and use its already composed Runtime. No
    # InMemory ResourcePlane, injected client, fake authorizer or fake transport.
    from app.main import app, runtime
    from contracts.capability import CapabilityInvocation
    from contracts.local_runtime import LocalRuntimeAuthorizationRef, LocalRuntimeExecutionLimits
    from contracts.resource_signing import build_resource_signature
    import httpx

    state = read_json(run / 'state.json')
    observed = snapshot(state)
    assert observed['coreReady'], observed
    results = {'N01A-01': {'status': 'PASS', 'evidence': observed},
               'N01A-02': {'status': 'PASS', 'health': observed['services']['ai']['health']},
               'N01A-03': {'status': 'PASS', 'health': observed['services']['host']['health']}}
    limits = LocalRuntimeExecutionLimits(timeoutSeconds=10, maxStdoutBytes=4096, maxStderrBytes=4096)
    authorization = runtime.local_runtime_authorization

    async def invoke(capability, arguments, auth=None):
        return await runtime.local_runtime_client.execute(
            CapabilityInvocation(invocationId=str(uuid4()), capabilityId=capability, input=arguments),
            resource_id='n01a-host', authorization=auth or authorization,
            limits=limits, idempotency_key=str(uuid4()))

    def passed(result):
        assert result.status == 'completed', result
        return result.output

    def denied(result, code):
        assert result.status == 'failed' and result.error.code == code, result
        return result.error.code

    async with app.router.lifespan_context(app):
        passed(await invoke('fs.write', {'path': 'files/hello.txt', 'content': 'alpha\nbeta\n',
                                        'overwrite': True, 'createParents': True}))
        read = passed(await invoke('fs.read', {'path': 'files/hello.txt'}))
        assert read['content'] == 'alpha\nbeta\n'
        passed(await invoke('fs.patch', {'path': 'files/hello.txt', 'patch': '@@ -1,2 +1,2 @@\n alpha\n-beta\n+gamma\n'}))
        listed = passed(await invoke('fs.list', {'path': 'files'}))
        assert any(entry['path'] == 'files/hello.txt' for entry in listed['entries'])
        disk = (run / 'workspace/files/hello.txt').read_bytes()
        assert disk == b'alpha\ngamma\n', disk
        results['N01A-04'] = {'status': 'PASS', 'diskSha256': hashlib.sha256(disk).hexdigest(),
                              'diskBytes': len(disk), 'workflowDatabase': os.environ['AGENTOS_WORKFLOW_DB_PATH'],
                              'client': type(runtime.local_runtime_client).__name__,
                              'transport': type(runtime.local_runtime_transport).__name__}
        outside = run / 'outside'
        sentinel = outside / 'sentinel.txt'
        fixture = read_json(run / 'fixture-preparation.json')
        assert fixture['preparedAt'] < state['created'], 'Fixture must be prepared before Runtime startup'
        original = sentinel.read_bytes()
        assert hashlib.sha256(original).hexdigest() == fixture['sentinelSha256']
        sentinel_mtime = sentinel.stat().st_mtime_ns
        outside_entries = sorted(p.name for p in outside.iterdir())
        escape = denied(await invoke('fs.write', {'path': '../outside/escape.txt', 'content': 'bad', 'overwrite': True}),
                        'PATH_OUTSIDE_WORKSPACE')
        junction = run / 'workspace/junction'
        assert junction.is_junction() and junction.resolve() == outside.resolve()
        junction_code = denied(await invoke('fs.write', {'path': 'junction/sentinel.txt', 'content': 'bad', 'overwrite': True}),
                               'PATH_OUTSIDE_WORKSPACE')
        assert sentinel.read_bytes() == original and not (outside / 'escape.txt').exists()
        results['N01A-06'] = {'status': 'PASS', 'traversal': escape, 'junction': junction_code,
                              'outsideSha256': hashlib.sha256(sentinel.read_bytes()).hexdigest()}
        # Execution never creates or repairs fixtures. A privileged external
        # preparer may supply a real link, but the Runtime stays non-elevated.
        symlink = inspect_symlink(run)
        results['N01A-06']['fixturePreparedBeforeRuntime'] = True
        results['N01A-06']['symlink'] = symlink
        if symlink['status'] == 'BLOCKED':
            symlink['preparationWinerror'] = fixture['symlink'].get('winerror')
            results['N01A-06']['status'] = 'BLOCKED'
        else:
            target = 'symlink/sentinel.txt' if symlink['targetKind'] == 'directory' else 'symlink'
            cases = [('fs.read', {'path': target}),
                     ('fs.write', {'path': target, 'content': 'bad', 'overwrite': True}),
                     ('fs.patch', {'path': target, 'patch': '@@ -1 +1 @@\n-untouched\n+bad\n'})]
            if symlink['targetKind'] == 'directory':
                cases += [('fs.list', {'path': 'symlink'}),
                          ('fs.write', {'path': 'symlink/new.txt', 'content': 'bad', 'overwrite': False})]
            symlink['operations'] = []
            for capability, arguments in cases:
                result = await invoke(capability, arguments)
                code = denied(result, 'PATH_OUTSIDE_WORKSPACE')
                assert sentinel.read_bytes() == original and not (outside / 'new.txt').exists()
                assert sentinel.stat().st_mtime_ns == sentinel_mtime
                assert sorted(p.name for p in outside.iterdir()) == outside_entries
                symlink['operations'].append({'capability': capability, 'path': arguments['path'],
                                              'errorCode': code, 'status': 'PASS', 'noSideEffects': True})
        codes = []
        for grant, workspace, expected in [('absent', 'n01a-workspace', 'GRANT_NOT_FOUND'),
                                            ('n01a-grant', 'other', 'WORKSPACE_MISMATCH')]:
            codes.append(denied(await invoke('fs.write', {'path': 'denied.txt', 'content': 'bad', 'overwrite': True},
                                            LocalRuntimeAuthorizationRef(grantId=grant, workspaceId=workspace)), expected))

        # Adversarial envelopes must reach the real HTTP boundary, including
        # schema failures that a correct typed client rejects before sending.
        secret = credentials(run)['hmac']
        path = '/v1/executions'
        envelope = {'protocolVersion': '1', 'requestId': str(uuid4()), 'invocationId': str(uuid4()),
                    'resourceId': 'n01a-host', 'capabilityId': 'fs.write',
                    'authorization': {'grantId': 'n01a-grant', 'workspaceId': 'n01a-workspace'},
                    'input': {'path': 'negative.txt', 'content': 'bad', 'overwrite': True},
                    'limits': limits.model_dump(by_alias=True), 'idempotencyKey': str(uuid4())}

        async def raw(payload, *, nonce=None, invalid=False):
            body = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()
            timestamp = int(time.time())
            nonce = nonce or str(uuid4())
            signature = build_resource_signature(secret, method='POST', path=path,
                                                 timestamp=timestamp, nonce=nonce, body=body)
            headers = {'X-Resource-Credential': 'n01a-credential', 'X-Resource-Timestamp': str(timestamp),
                       'X-Resource-Nonce': nonce, 'X-Resource-Signature': '0' * 64 if invalid else signature,
                       'Content-Type': 'application/json', 'Idempotency-Key': payload['idempotencyKey']}
            async with httpx.AsyncClient(trust_env=False) as client:
                response = await client.post(f"http://127.0.0.1:{state['hostPort']}{path}", content=body, headers=headers)
                return response.status_code, response.json()

        status, invalid = await raw(envelope, invalid=True)
        assert status == 401 and invalid['error']['code'] == 'AUTHENTICATION_FAILED'
        assert not (run / 'workspace/negative.txt').exists()
        # Consume a nonce with a denied grant so even its first use has no write.
        replay_payload = dict(envelope, authorization={'grantId': 'absent', 'workspaceId': 'n01a-workspace'})
        nonce = str(uuid4())
        first_status, first = await raw(replay_payload, nonce=nonce)
        status, replayed = await raw(replay_payload, nonce=nonce)
        assert first['error']['code'] == 'GRANT_NOT_FOUND', first
        assert status == 409 and replayed['error']['code'] == 'REPLAY_REJECTED'
        assert (run / 'workspace/files/hello.txt').read_bytes() == disk
        assert not (run / 'workspace/negative.txt').exists()
        results['N01A-05'] = {'status': 'PASS', 'badSignature': invalid['error']['code'],
                              'replayedNonce': replayed['error']['code'], 'diskUnchanged': True}
        missing = dict(envelope)
        missing.pop('authorization')
        status, rejection = await raw(missing)
        assert status >= 400 and rejection['error']['code'] == 'PROTOCOL_MISMATCH', rejection
        inline = dict(envelope, input=dict(envelope['input'], allowedRoot=str(outside)))
        status, inline_rejection = await raw(inline)
        assert status >= 400 and inline_rejection['error']['code'] == 'PROTOCOL_MISMATCH'
        status, wrong_resource = await raw(dict(envelope, resourceId='other-resource'))
        assert wrong_resource['error']['code'] == 'RESOURCE_MISMATCH'
        assert not (run / 'workspace/denied.txt').exists() and sentinel.read_bytes() == original
        results['N01A-07'] = {'status': 'PASS', 'errors': codes + [rejection['error']['code']],
                              'inlineRoot': inline_rejection['error']['code'], 'wrongResource': wrong_resource['error']['code']}
        assert sentinel.stat().st_mtime_ns == sentinel_mtime
        assert sorted(p.name for p in outside.iterdir()) == outside_entries
        results['N01A-06']['sentinelUnchanged'] = {
            'sha256': hashlib.sha256(sentinel.read_bytes()).hexdigest(),
            'mtimeNs': sentinel_mtime, 'directoryEntries': outside_entries, 'status': 'PASS'}
    # Contest the original running AI's workflow DB with another full Uvicorn.
    contender_env = environment(run, state, credentials(run))
    contender = spawn(run, 'contender', [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1',
                                        '--port', '18762', '--workers', '1'], contender_env)
    try:
        import psutil
        process = owned(contender)
        exit_code = process.wait(30) if process else 1
        assert exit_code != 0
        log = (run / 'contender.log').read_text(encoding='utf-8')
        assert 'another AgentOS runtime owns' in log, log
        assert snapshot(state)['coreReady']
        results['N01A-08'] = {'status': 'PASS', 'exitCode': exit_code, 'firstRuntimeHealthy': True,
                              'process': contender}
    finally:
        stop(contender)
    write_json(run / f'smoke-{invocation_id}.json', {'invocationId': invocation_id, 'checks': results})


if __name__ == '__main__':
    run = Path(sys.argv[1])
    invocation_id = sys.argv[2]
    try:
        asyncio.run(exercise(run, invocation_id))
    except Exception as exc:
        write_json(run / f'smoke-{invocation_id}.json', {
            'invocationId': invocation_id, 'status': 'FAIL', 'checks': {},
            'errorType': type(exc).__name__, 'reason': str(exc)})
        traceback.print_exc()
        raise SystemExit(1)
