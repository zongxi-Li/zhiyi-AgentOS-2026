"""Agent admission checks shared by registration, planning and READY execution."""

from types import SimpleNamespace
import asyncio

import pytest

from adapters.agent_invocation import AgentInvocationAdapter, AgentInvocationError
from components.planner.cognitive_router import CognitiveRouter
from runtime.acg_execution import ACGExecutionService
from service.agents import AgentNotFound, AgentOutput, AgentProfile, AgentRegistry, BaseAgent
from support.acg.capabilities import PlanningCapabilityDescriptor


class _Agent(BaseAgent):
    async def run(self, context):
        raise AssertionError("eligibility checks must not invoke an Agent")


def _agent(name, capabilities=(), *, enabled=True, priority=0, domain="general"):
    return _Agent(AgentProfile(
        agentId=name, agentName=name, domain=domain,
        capabilities=list(capabilities), enabled=enabled, bindingPriority=priority,
    ))


def test_named_agent_must_satisfy_requested_capability():
    registry = AgentRegistry()
    writer = _agent("writer", ("writing",))
    analyst = _agent("analyst", ("analysis",))
    registry.register(writer)
    registry.register(analyst)

    assert registry.resolve("general", "writer", "analysis") is analyst
    assert registry.resolve("general", "writer", " WRITING ") is writer


def test_unnamed_capability_is_not_a_wildcard_for_legacy_agents():
    registry = AgentRegistry()
    legacy = _agent("legacy")
    registry.register(legacy)

    assert registry.resolve("general", "legacy") is legacy
    with pytest.raises(AgentNotFound):
        registry.resolve("general", "legacy", "analysis")


def test_disabled_agents_cannot_be_resolved_or_widen_the_scope():
    registry = AgentRegistry()
    registry.register(_agent("disabled", ("analysis",), enabled=False))
    available = _agent("available", ("analysis",))
    registry.register(available)

    assert registry.resolve("general", "disabled", "analysis") is available
    with pytest.raises(AgentNotFound):
        registry.resolve_by_id("disabled")
    with pytest.raises(AgentNotFound):
        registry.scoped(["disabled"]).resolve("general", capability="analysis")


def test_ready_role_hint_cannot_override_capability_or_scope():
    registry = AgentRegistry()
    registry.register(_agent("writer", ("writing",)))
    analyst = _agent("analyst", ("analysis",))
    registry.register(analyst)
    service = SimpleNamespace(agent_registry=registry)
    run = SimpleNamespace(domain="general", execution_scope=None, execution_state={})
    step = SimpleNamespace(step_id="analyse", agent_name="writer", capability="analysis")

    assert ACGExecutionService._resolve_embedded_agent(
        service, run=run, step=step, role_hint="writer"
    ) is analyst
    run.execution_scope = SimpleNamespace(agent_ids=["writer"])
    with pytest.raises(AgentNotFound):
        ACGExecutionService._resolve_embedded_agent(
            service, run=run, step=step, role_hint="writer"
        )


def test_historical_agent_binding_must_still_satisfy_capability():
    registry = AgentRegistry()
    registry.register(_agent("writer", ("writing",)))
    analyst = _agent("analyst", ("analysis",))
    registry.register(analyst)
    run = SimpleNamespace(
        domain="general", execution_scope=None,
        execution_state={"resourceBindings": {"analyse": "writer"}},
    )
    step = SimpleNamespace(step_id="analyse", agent_name="", capability="analysis")

    assert ACGExecutionService._resolve_embedded_agent(
        SimpleNamespace(agent_registry=registry), run=run, step=step, role_hint=None
    ) is analyst


def test_planning_filters_disabled_before_ranking_and_respects_empty_candidates():
    registry = AgentRegistry()
    registry.register(_agent("disabled", ("analysis",), enabled=False, priority=100))
    registry.register(_agent("available", ("analysis",)))
    router = CognitiveRouter(registry)
    descriptor = PlanningCapabilityDescriptor(
        capabilityId="analysis", displayName="Analysis",
    )

    assert [c.agent_name for c in router.candidates_for(descriptor, domain="general")] == ["available"]
    assert router.candidates_for(descriptor, domain="general", agents=[]) == []


def test_disabling_selected_agent_blocks_invocation_with_trusted_not_invoked_proof():
    registry = AgentRegistry()
    agent = _agent("selected", ("analysis",))
    registry.register(agent)
    selected = registry.resolve("general", "selected", "analysis")
    invoker = AgentInvocationAdapter(registry=registry.scoped(["selected"]))
    context = SimpleNamespace(step=SimpleNamespace(step_id="one", agent_name="selected"))
    agent.profile.enabled = False

    with pytest.raises(AgentInvocationError) as captured:
        asyncio.run(invoker.invoke(context=context, agent=selected))

    assert captured.value.code == "AGENT_NOT_IN_SCOPE"
    assert invoker.consume_not_invoked(captured.value, context)
    assert not invoker.consume_not_invoked(captured.value, context)


def test_disabling_agent_does_not_cancel_an_already_entered_run():
    async def execute():
        entered, release = asyncio.Event(), asyncio.Event()

        class RunningAgent(BaseAgent):
            async def run(self, context):
                entered.set()
                await release.wait()
                return AgentOutput(output={"completed": True})

        registry = AgentRegistry()
        agent = RunningAgent(AgentProfile(agentName="running", domain="general"))
        registry.register(agent)
        invoker = AgentInvocationAdapter(registry=registry)
        context = SimpleNamespace(step=SimpleNamespace(step_id="one", agent_name="running"))
        active = asyncio.create_task(invoker.invoke(context=context, agent=agent))
        await entered.wait()
        agent.profile.enabled = False
        release.set()
        assert (await active).output == {"completed": True}
        with pytest.raises(AgentInvocationError):
            await invoker.invoke(context=context, agent=agent)

    asyncio.run(asyncio.wait_for(execute(), 2))
