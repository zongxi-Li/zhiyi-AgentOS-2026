"""Host faults retain their cause and isolate only the affected authority."""
import pytest

from adapters.guarded_tool import ToolInvocationError
from adapters.hands_http import HandsOutcomeUnknown
from components.recovery import failure_event_from_exception
from components.resource.scheduler.models import SchedulerUnavailable
from contracts.tools import HostToolExecutionError
from test_unified_tools import stack, node, context_for, GeneralAgent


@pytest.mark.asyncio
async def test_disabled_hands_is_eligibility_failure_with_exact_tool_attribution(stack):
    stack.runtime.resource_plane.set_runtime_enabled('hands', enabled=False)
    runner, state, step, http = node(stack, GeneralAgent(),
        [[('fs.read', {'path': 'note.txt'})], {'answer': 'must not run'}])
    with pytest.raises(RuntimeError) as caught:
        await runner(step.step_id, state)
    failure = failure_event_from_exception(caught.value, subject_ref='run:test')
    assert failure.reason_code == 'NO_ELIGIBLE_RESOURCE'
    assert failure.source.value == 'scheduler' and failure.retryable is False
    assert failure.details['tool'] == 'fs.read'
    assert failure.details['resourceId'] == 'hands'
    assert failure.details['stepId'] == step.step_id
    assert failure.details['phase'] == 'tool_scheduling'
    assert {'resourceId': 'hands', 'reasons': ['DISABLED']} in failure.details['candidateReasons']
    assert len(http.requests) == 1 and stack.service.requests == []
    assert stack.runtime.resource_binder.coordinator.active_slots('hands') == 0


@pytest.mark.asyncio
async def test_scheduler_exception_retains_tool_dependency_before_dispatch(stack):
    async def unavailable(**kwargs):
        raise SchedulerUnavailable('coordination store unavailable')
    stack.runtime.resource_binder.wait_ready = unavailable
    runner, _, step, _ = node(stack, GeneralAgent())
    with pytest.raises(HostToolExecutionError) as caught:
        await context_for(runner, step).tool_runtime.execute('fs.read', {'path': 'note.txt'}, operation_key='not-admitted')
    assert caught.value.code == 'SCHEDULER_UNAVAILABLE' and caught.value.retryable is True
    assert caught.value.details['resourceId'] == 'hands'
    assert caught.value.details['phase'] == 'tool_scheduling'
    assert caught.value.details['operationKey'] == 'not-admitted'
    assert stack.service.requests == []
    assert stack.runtime.execution_value_store.get_tool_value(run_id=runner.run.run_id, key='not-admitted:request') is None


@pytest.mark.asyncio
@pytest.mark.parametrize('name,arguments,reason,scope,quarantined', [
    ('fs.read', {'path': 'note.txt'}, 'transport_unavailable', 'operation', False),
    ('fs.list', {'path': '.'}, 'transport_unavailable', 'operation', False),
    ('fs.write', {'path': 'note.txt', 'content': 'new'}, 'transport_unavailable', 'operation', True),
    ('shell.exec', {'command': 'mock'}, 'transport_unavailable', 'operation', True),
    ('fs.read', {'path': 'note.txt'}, 'protocol_integrity', 'runtime', True),
    ('fs.read', {'path': 'note.txt'}, 'execution_unknown', 'runtime', True),
])
async def test_unknown_outcome_scope_follows_trusted_effect_and_failure_class(
        stack, name, arguments, reason, scope, quarantined):
    async def uncertain(*args, **kwargs):
        raise HandsOutcomeUnknown('injected transport or receipt failure',
            reconciliation_reason=reason, quarantine_scope=scope)
    stack.runtime.local_runtime_transport.execute_with_identity = uncertain
    runner, _, step, _ = node(stack, GeneralAgent())
    context = context_for(runner, step)
    with pytest.raises(ToolInvocationError) as caught:
        await context.tool_runtime.execute(name, arguments, operation_key='uncertain')
    assert caught.value.code == 'HANDS_OUTCOME_UNKNOWN'
    assert caught.value.retryable is False
    assert caught.value.details['resourceId'] == 'hands'
    assert caught.value.details['tool'] == name
    assert stack.runtime.resource_plane.runtime('hands').enabled is not quarantined
    assert stack.runtime.resource_binder.coordinator.active_slots('hands') == int(quarantined)
    store = stack.runtime.execution_value_store
    unsettled = store.get_tool_value(run_id=runner.run.run_id, key='uncertain:unsettled')
    assert unsettled['quarantineScope'] == ('runtime' if quarantined else 'operation')
    assert unsettled['reconciliationReason'] == reason
    assert store.get_tool_value(run_id=runner.run.run_id, key='uncertain:request') is not None
    assert store.get_tool_value(run_id=runner.run.run_id, key='uncertain:receipt') is None
    assert store.get_tool_value(run_id=runner.run.run_id, key='uncertain:result') is None
    if not quarantined:
        # An unrelated node can still use the host after one read loses contact.
        del stack.runtime.local_runtime_transport.execute_with_identity
        result = await context.tool_runtime.execute('fs.read', {'path': 'other.txt'}, operation_key='other')
        assert result.data['status'] == 'completed'
