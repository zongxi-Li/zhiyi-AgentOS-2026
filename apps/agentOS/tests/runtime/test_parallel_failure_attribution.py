"""Parallel completion order must not hide a reconciliation blocker."""
from types import SimpleNamespace
import pytest

from components.executor.graph import ACGExecutionState, ACGSuperstepError
from contracts.tools import HostToolExecutionError
from contracts.workflow import RuntimeRunRecord, WorkflowStep, StepStatus
from runtime.runtime_recovery import RuntimeRecoveryCoordinator


@pytest.mark.parametrize('first_code,second_code,action', [
    ('NO_ELIGIBLE_RESOURCE', 'HANDS_OUTCOME_UNKNOWN', 'abort'),
    ('HANDS_OUTCOME_UNKNOWN', 'EXECUTION_AUTHORIZATION_LOST', 'review'),
])
def test_all_parallel_faults_are_persisted_and_strongest_blocker_is_primary(first_code, second_code, action):
    capacity = HostToolExecutionError(first_code, 'first backend failure',
        details={'stepId': 'first', 'tool': 'fs.read', 'resourceId': 'hands'})
    unknown = HostToolExecutionError(second_code, 'second backend failure',
        details={'stepId': 'second', 'tool': 'fs.write', 'resourceId': 'hands'})
    error = ACGSuperstepError(failed_step_ids=('first', 'second'), cancelled_step_ids=(),
        cause=capacity, causes=(capacity, unknown), step_causes={'first': capacity, 'second': unknown})
    run = RuntimeRunRecord(runId='run', missionId='mission', workflowId='workflow', domain='general', runtimeEngine='acg',
        steps=[WorkflowStep(stepId=key, name=key, agentName='agent', status=StepStatus.FAILED)
               for key in ('first', 'second')])
    saved = []
    coordinator = RuntimeRecoveryCoordinator.__new__(RuntimeRecoveryCoordinator)
    coordinator.ports = SimpleNamespace(workflow_store=SimpleNamespace(save_run=saved.append))
    coordinator._terminalize_active_execution = lambda *args: None
    coordinator.record_execution_failure(run, ACGExecutionState(runId='run'), error)
    facts = run.execution_state['failureEvents']
    assert len(facts) == 2
    assert {fact['subjectRef'] for fact in facts} == {'run:run:step:first', 'run:run:step:second'}
    assert facts[-1]['reasonCode'] == second_code
    assert facts[-1]['details']['stepId'] == 'second'
    assert run.execution_state['recoveryOutcome']['action'] == action
    assert run.execution_state['recoveryOutcome']['failureId'] == facts[-1]['failureId']
    assert saved == [run]
