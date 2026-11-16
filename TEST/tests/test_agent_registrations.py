"""Versioned local registrations preserve legacy lookup and exact identity."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from adapters.agent.invocation import AgentInvocationAdapter, AgentInvocationError
from adapters.agent import AgentNotFound, AgentOutput, AgentProfile, AgentRegistry, BaseAgent


class _Agent(BaseAgent):
    def __init__(self, profile, label="original"):
        super().__init__(profile)
        self.label = label
        self.calls = []

    async def run(self, context):
        self.calls.append(context.step.step_id)
        return AgentOutput(output={"label": self.label})


def _agent(*, version=None, label="original", capabilities=("analysis",), **fields):
    return _Agent(AgentProfile(agentId="analyst", agentName="analyst", domain="general",
                               capabilities=list(capabilities), definitionVersion=version, **fields), label)


def _context(ref=None):
    return SimpleNamespace(step=SimpleNamespace(step_id="step", agent_name="analyst", capability="analysis"),
                           workflow=SimpleNamespace(domain="general"), agent_registration=ref)


def test_legacy_register_remains_none_and_creates_an_immutable_definition():
    registry, agent = AgentRegistry(), _agent()
    assert registry.register(agent) is None
    ref = registry.registration_for(agent)
    definition = registry.definitions()[0]
    assert registry.resolve("general", "analyst", "analysis") is agent
    assert registry.resolve_by_id("analyst") is agent
    assert definition.definition_version is None  # unknown, not an invented version
    assert definition.execution_mode == "unspecified"
    agent.profile.capabilities.append("writing")
    assert definition.capabilities == ("analysis",)
    with pytest.raises(ValidationError):
        definition.domain = "other"
    with pytest.raises(AgentNotFound, match="declaration changed"):
        registry.resolve_registration(ref)


def test_registration_idempotence_and_replacement_are_distinct_from_definition_version():
    registry, first = AgentRegistry(), _agent(version="1")
    registry.register(first)
    one = registry.registration_for(first)
    registry.register(first)
    assert registry.registration_for(first) == one
    second = _agent(version="1", label="replacement")
    registry.register(second)
    two = registry.registration_for(second)
    assert two.instance_id == one.instance_id and two.generation == one.generation + 1
    assert two.definition_digest == one.definition_digest
    assert two.resource_id != one.resource_id
    assert len(registry.definitions()) == 1
    with pytest.raises(AgentNotFound):
        registry.resolve_registration(one)


def test_versioned_declarations_cannot_be_rewritten_but_multiple_versions_can_coexist():
    registry = AgentRegistry()
    first = _agent(version="1")
    registry.register_instance(first, instance_id="one")
    second = _agent(version="2", capabilities=("analysis", "writing"))
    registry.register_instance(second, instance_id="two")
    assert len(registry.registrations()) == len(registry.definitions()) == 2
    assert registry.resolve_by_id("analyst") is first  # explicit first-instance default
    with pytest.raises(ValueError, match="definition version conflicts"):
        registry.register_instance(_agent(version="1", capabilities=("writing",)), instance_id="three")
    assert len(registry.registrations()) == 2


def test_scope_applies_to_exact_registration_and_instance_views():
    registry, agent = AgentRegistry(), _agent()
    registry.register(agent)
    ref = registry.registration_for(agent)
    assert registry.scoped(["analyst"]).resolve_registration(ref) is agent
    outside = registry.scoped([])
    assert outside.registrations() == ()
    with pytest.raises(AgentNotFound):
        outside.resolve_registration(ref)
    with pytest.raises(AgentNotFound):
        outside.registration_for(agent)


def test_stale_selected_object_and_ref_cannot_invoke_replacement_or_mint_false_effects():
    registry, first = AgentRegistry(), _agent()
    registry.register(first)
    ref = registry.registration_for(first)
    second = _agent(label="replacement")
    registry.register(second)
    invoker = AgentInvocationAdapter(registry=registry)
    for context, supplied in ((_context(ref), first), (_context(ref), None), (_context(), first)):
        with pytest.raises(AgentInvocationError) as error:
            asyncio.run(invoker.invoke(context=context, agent=supplied))
        assert invoker.consume_not_invoked(error.value, context)
    assert first.calls == second.calls == []
    result = asyncio.run(invoker.invoke(context=_context(registry.registration_for(second)), agent=second))
    assert result.output == {"label": "replacement"}


def test_mutating_and_reregistering_same_object_invalidates_the_previous_ref():
    registry, agent = AgentRegistry(), _agent()
    registry.register(agent)
    first = registry.registration_for(agent)
    agent.profile.model_name = "changed-model"
    registry.register(agent)
    second = registry.registration_for(agent)
    assert second.generation == first.generation + 1
    with pytest.raises(AgentNotFound):
        registry.resolve_registration(first)


def test_concurrent_replace_uses_expected_generation_and_publishes_only_one_winner():
    registry, agent = AgentRegistry(), _agent()
    registry.register(agent)
    ref = registry.registration_for(agent)

    def replace(label):
        try:
            return registry.register_instance(_agent(label=label), instance_id=ref.instance_id,
                                               expected_generation=ref.generation)
        except ValueError as error:
            assert "generation conflict" in str(error)
            return None

    with ThreadPoolExecutor(2) as executor:
        results = list(executor.map(replace, ("a", "b")))
    assert sum(item is not None for item in results) == 1
    assert registry.registrations()[0].ref.generation == ref.generation + 1


def test_unregister_fences_late_cleanup_and_avoids_generation_aba():
    registry, first = AgentRegistry(), _agent()
    registry.register(first)
    old = registry.registration_for(first)
    registry.unregister_instance(old)
    assert registry.all() == ()
    replacement = _agent()
    new = registry.register_instance(replacement, instance_id=old.instance_id)
    assert new.generation > old.generation
    with pytest.raises(AgentNotFound):
        registry.unregister_instance(old)
    assert registry.resolve_registration(new) is replacement


def test_registry_epoch_prevents_restarted_generation_one_from_reusing_old_identity():
    first, second = AgentRegistry(), AgentRegistry()
    first.register(_agent())
    second.register(_agent())
    a, b = first.registrations()[0].ref, second.registrations()[0].ref
    assert a.instance_id == b.instance_id and a.generation == b.generation == 1
    assert a.registry_id != b.registry_id and a.resource_id != b.resource_id
    with pytest.raises(AgentNotFound):
        second.resolve_registration(a)


def test_one_object_cannot_inflate_multiple_instances_and_failed_default_change_is_atomic():
    registry, agent = AgentRegistry(), _agent()
    registry.register_instance(agent, instance_id="one")
    before = registry.registrations()
    with pytest.raises(ValueError, match="multiple Agent instances"):
        registry.register_instance(agent, instance_id="two")
    with pytest.raises(ValueError, match="default instance"):
        registry.register_instance(_agent(), instance_id="three", make_default=True)
    assert registry.registrations() == before


def test_secondary_instance_cannot_take_over_another_plugins_logical_identity():
    registry = AgentRegistry()
    registry.register_instance(_agent(source="plugin", pluginId="one"), instance_id="one")
    with pytest.raises(ValueError, match="owner cannot change"):
        registry.register_instance(_agent(source="plugin", pluginId="two"), instance_id="two")


def test_deletion_does_not_erase_owner_version_or_replacement_cas_constraints():
    registry, agent = AgentRegistry(), _agent(version="1", source="plugin", pluginId="one")
    registry.register(agent)
    ref = registry.registration_for(agent)
    registry.unregister_instance(ref)
    with pytest.raises(ValueError, match="generation conflict"):
        registry.register_instance(_agent(version="1", source="plugin", pluginId="one"),
                                   instance_id=ref.instance_id, expected_generation=ref.generation)
    with pytest.raises(ValueError, match="owner cannot change"):
        registry.register_instance(_agent(source="plugin", pluginId="two"), instance_id="other")
    with pytest.raises(ValueError, match="definition version conflicts"):
        registry.register_instance(_agent(version="1", capabilities=("writing",), source="plugin", pluginId="one"),
                                   instance_id="other")


def test_replacing_registering_or_upgrading_cannot_implicitly_enable_a_disabled_agent():
    registry, agent = AgentRegistry(), _agent(version="1")
    registry.register(agent)
    registry.set_enabled("analyst", enabled=False)
    registry.register(_agent(version="1"))
    registry.register_instance(_agent(version="2"), instance_id="other")
    assert not registry.is_enabled("analyst")
    for item in registry.registrations():
        with pytest.raises(AgentNotFound):
            registry.resolve_registration(item.ref)
    registry.set_enabled("analyst", enabled=True)
    assert registry.resolve_by_id("analyst").profile.enabled
    assert all(registry.resolve_registration(item.ref) for item in registry.registrations())


def test_initial_pack_stamping_updates_snapshot_and_is_rejected_after_binding():
    registry, agent = AgentRegistry(), _agent()
    registry.register(agent)
    registry.stamp_plugin(agent, plugin_id="one", plugin_version="1", contribution_id="analyst")
    item, = registry.registrations()
    assert item.definition.source == "plugin" and item.definition.plugin_id == "one"
    assert registry.bind(agent) == item.ref

    other, native = AgentRegistry(), _agent()
    other.register(native)
    other.bind(native)
    with pytest.raises(ValueError, match="initial assembly"):
        other.stamp_plugin(native, plugin_id="two", plugin_version="1", contribution_id="analyst")
    assert native.profile.source == "native"


def test_default_views_preserve_order_and_do_not_promote_a_secondary_instance_on_delete():
    registry, first, secondary = AgentRegistry(), _agent(), _agent()
    writer = _Agent(AgentProfile(agentId="writer", agentName="writer", domain="general", capabilities=["writing"]))
    registry.register_instance(first, instance_id="one")
    registry.register(writer)
    registry.register_instance(secondary, instance_id="two")
    assert registry.all() == (first, writer)

    replacement = _agent(label="replacement")
    registry.register(replacement)
    assert registry.all() == (replacement, writer)
    assert registry.resolve("general", "analyst") is replacement
    assert registry.scoped(["analyst"]).all() == (replacement,)

    registry.unregister_instance(registry.registration_for(replacement))
    assert registry.all() == (writer,)
    with pytest.raises(AgentNotFound):
        registry.resolve_by_id("analyst")
    registry.register_instance(secondary, instance_id="two")
    assert registry.all() == (writer, secondary)
    assert registry.resolve_by_id("analyst") is secondary


def test_registration_metadata_lookup_respects_scope_without_admitting_or_binding_an_agent():
    registry, agent = AgentRegistry(), _agent()
    registry.register(agent)
    ref = registry.registration_for(agent)
    item = registry.get_registration(ref)
    assert item.implementation is agent and item.ref == ref
    assert registry.scoped(["analyst"]).get_registration(ref) is item
    with pytest.raises(AgentNotFound):
        registry.scoped([]).get_registration(ref)

    registry.set_enabled("analyst", enabled=False)
    assert registry.get_registration(ref) is item
    with pytest.raises(AgentNotFound):
        registry.resolve_registration(ref)
    registry.set_enabled("analyst", enabled=True)
    registry.stamp_plugin(agent, plugin_id="one", plugin_version="1", contribution_id="analyst")
    with pytest.raises(AgentNotFound):
        registry.get_registration(ref)
    assert registry.get_registration(registry.registration_for(agent)).definition.source == "plugin"
