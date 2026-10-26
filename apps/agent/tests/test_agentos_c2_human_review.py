"""Explicit user review policy through the accepted C2 graph and Native review."""
import hashlib
import pytest

from test_agentos_c2_http import PREFIX, CONTRACT, WORKFLOW_ID, accepted, materialize, base, activation_body, server
from test_agentos_c2_dispatch_http import database, endpoint, wait_run
from test_agentos_c2_final_delivery import final_delivery_setup
from test_agentos_c2_permit_http import handoff, issue, ready_resource, trusted_call


def create_review_run(client, mode='human_in_loop'):
    response = client.post(PREFIX + '/missions', json={
        'title': 'Explicit user review before delivery', 'workflowId': WORKFLOW_ID,
        'reviewMode': mode, 'clientRequestId': 'review-policy',
        'input': {'contractText': CONTRACT, 'deterministicIntent': True},
        'semantics': {'objective': 'Review the contract and produce a traceable report',
                      'constraints': [], 'sourceRefs': ['input:contractText']},
    })
    assert response.status_code == 202, response.text
    return response.json()


def dispatch_review_run(client, runtime, created):
    control = accepted(client, created)
    mat, _ = materialize(client, created, control)
    activation = client.post(base(created) + '/activation', json=activation_body(mat))
    assert activation.status_code == 200, activation.text
    h, _ = handoff(client, created, mat, activation.json())
    permit, _ = issue(client, created, mat, h)
    trusted_call(client, ready_resource, runtime, created['runId'])
    current = client.get(PREFIX + '/runs/' + created['runId']).json()
    request = {'operationId': 'dispatch', 'expectedPermitId': permit['permitId'],
               'expectedGraphId': mat['graphId'], 'expectedGraphVersion': mat['graphVersion'],
               'expectedRuntimeRevision': current['runtimeRevision']}
    response = client.post(endpoint(created), json=request)
    assert response.status_code == 202, response.text
    return request


def test_human_in_loop_is_a_formal_review_barrier_before_final(tmp_path):
    database(tmp_path)
    with server(tmp_path, dispatch=True, setup=final_delivery_setup) as (client, runtime, agent):
        created = create_review_run(client)
        request = dispatch_review_run(client, runtime, created)
        run = wait_run(client, created)
        assert run['status'] == 'waiting_review', run
        assert agent.calls == ['A']
        persisted = runtime.workflow_store.get_run(created['runId'])
        assert persisted.review_mode == 'human_in_loop'
        assert all(step.requires_review for step in persisted.steps)
        assert client.get(PREFIX + '/runs/' + created['runId'] + '/artifacts').json()['items'] == []
        assert client.post(endpoint(created), json=request).status_code == 202
        assert agent.calls == ['A']
        commit = trusted_call(client, runtime.planning_commit_authority.get_commit,
                              client.get(PREFIX + '/runs/' + created['runId']).json()['formalControl']['commitId'])
        policy = commit.source_provenance.lowering_options['reviewPolicy']
        assert policy['policyVersion'] == 'human-review-all-steps-v1'
        assert policy['source'] == 'run.reviewMode'
        assert all(n.constraints[-1]['policyVersion'] == policy['policyVersion'] for n in commit.proposal_payload.nodes)
    # Reconstruct every service/Authority; approval uses the accepted command,
    # not a fresh Dispatch or an in-memory identity from the previous process.
    with server(tmp_path, dispatch=True, setup=final_delivery_setup) as (client, runtime, agent):
        url = PREFIX + '/runs/' + created['runId']
        first = {'stepId': 'A', 'decision': 'approved', 'operationId': 'approve-A'}
        denied = client.post(url + '/reviews', json=first, headers={'X-Authenticated-User-Id': 'intruder'})
        assert denied.status_code in {403, 404} and not agent.calls
        for step, expected_calls in [('A', ['B']), ('B', ['B', 'C']), ('C', ['B', 'C'])]:
            before = client.get(url + '/artifacts').json()['items']
            assert not [a for a in before if a['artifactType'] == 'run_deliverable'], before
            if step == 'C':
                # Sealed bytes and the internal Identity are review evidence;
                # neither direct content URLs nor Workspace may publish final.
                manifests = runtime.content_manifest_store.list_manifests(owner_type='run', owner_id=created['runId'])
                assert manifests
                for manifest in manifests:
                    for suffix in ['', '/download', '/fragments']:
                        assert client.get(url + '/artifacts/' + manifest.manifest_id + suffix).status_code == 404
                workspace = client.get(PREFIX + '/missions/' + created['missionId'] + '/workspace', params={'runId': created['runId']}).json()
                assert not [e for e in workspace['entries'] if e.get('artifactKey') == 'final']
            body = {'stepId': step, 'decision': 'approved', 'operationId': 'approve-' + step,
                    'reviewer': 'forged-reviewer-label'}
            response = client.post(url + '/reviews', json=body)
            assert response.status_code == 200, response.text
            assert agent.calls == expected_calls
            # Simulate a lost ACK: retry the same accepted review decision.
            replay = client.post(url + '/reviews', json=body)
            assert replay.status_code == 200, replay.text
            assert agent.calls == expected_calls
            assert client.post(endpoint(created), json=request).status_code == 202
            assert agent.calls == expected_calls
        assert client.get(url).json()['status'] == 'completed'
        persisted = runtime.workflow_store.get_run(created['runId'])
        decisions = [e for e in persisted.trace if e.event_type.value == 'review_decided']
        assert len(decisions) == 3 and all(e.payload['reviewer'] == 'owner' for e in decisions)
        finals = [a for a in client.get(url + '/artifacts').json()['items'] if a['artifactType'] == 'run_deliverable']
        assert len(finals) == 1 and finals[0]['sealed']
        content = client.get(url + '/artifacts/' + finals[0]['manifestId'] + '/download')
        assert content.status_code == 200 and hashlib.sha256(content.content).hexdigest() == finals[0]['checksum']


def test_auto_policy_retains_uninterrupted_execution(tmp_path):
    database(tmp_path)
    with server(tmp_path, dispatch=True, setup=final_delivery_setup) as (client, runtime, agent):
        created = create_review_run(client, 'auto')
        dispatch_review_run(client, runtime, created)
        assert wait_run(client, created)['status'] == 'completed'
        assert agent.calls == ['A', 'B', 'C']


@pytest.mark.parametrize('decision', ['rejected', 'cancel'])
def test_human_review_rejection_or_cancel_never_reexecutes(tmp_path, decision):
    database(tmp_path)
    with server(tmp_path, dispatch=True, setup=final_delivery_setup) as (client, runtime, agent):
        created = create_review_run(client)
        request = dispatch_review_run(client, runtime, created)
        assert wait_run(client, created)['status'] == 'waiting_review'
        url = PREFIX + '/runs/' + created['runId']
        if decision == 'cancel':
            response = client.post(url + '/cancel')
        else:
            body = {'stepId': 'A', 'decision': decision, 'operationId': 'reject-A'}
            response = client.post(url + '/reviews', json=body)
        assert response.status_code == 200, response.text
        assert client.post(endpoint(created), json=request).status_code in {202, 409}
        assert agent.calls == ['A']
        assert client.get(url).json()['status'] in {'cancelled', 'failed'}
        assert client.get(url + '/artifacts').json()['items'] == []


def test_old_permit_cannot_be_reinterpreted_as_manual_review(tmp_path):
    database(tmp_path)
    with server(tmp_path, dispatch=True, setup=final_delivery_setup) as (client, runtime, agent):
        from test_agentos_c2_dispatch_http import permitted
        created, request = permitted(client)
        def drift():
            run = runtime.workflow_store.get_run(created['runId'])
            run.review_mode = 'human_in_loop'
            runtime.workflow_store.save_run(run)
        trusted_call(client, drift)
        assert client.post(endpoint(created), json=request).status_code == 409
        assert not agent.calls and not runtime.execution_dispatch_store.commands()


def test_conflicting_policy_fails_before_formal_acceptance(tmp_path, monkeypatch):
    database(tmp_path)
    import runtime.human_review_policy as policy
    monkeypatch.setattr(policy, 'bind_review_policy', lambda plan, mode: plan)
    with server(tmp_path, dispatch=True, setup=final_delivery_setup) as (client, runtime, agent):
        created = create_review_run(client)
        run = wait_run(client, created)
        assert run['status'] == 'failed'
        assert not run['formalControl']['commitId'] and not agent.calls


def test_review_write_revocation_rejects_before_any_persisted_effect(tmp_path, monkeypatch):
    from test_agentos_c2_permit_http import snapshot
    database(tmp_path)
    with server(tmp_path, dispatch=True, setup=final_delivery_setup) as (client, runtime, agent):
        created = create_review_run(client)
        dispatch_review_run(client, runtime, created)
        assert wait_run(client, created)['status'] == 'waiting_review'
        def denied(*args):
            raise PermissionError('write revoked')
        monkeypatch.setattr(runtime.mission_semantic_service, 'require_write_access', denied)
        before = snapshot(runtime)
        response = client.post(PREFIX + '/runs/' + created['runId'] + '/reviews', json={
            'stepId': 'A', 'decision': 'approved', 'operationId': 'revoked-approve'})
        assert response.status_code == 403, response.text
        assert snapshot(runtime) == before and agent.calls == ['A']
