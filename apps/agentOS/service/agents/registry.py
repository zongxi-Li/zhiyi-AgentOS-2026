"""Agent 服务注册表与运行范围视图。"""

from __future__ import annotations

from typing import Iterable, Optional
from dataclasses import dataclass
from threading import RLock
from uuid import uuid4
from collections.abc import Callable

from contracts.authority import LogicalAgentId
from contracts.agents import AgentDefinition, AgentRegistrationRef
from .base import BaseAgent


class AgentNotFound(KeyError):
    """当前领域、名称、能力或运行范围内没有可调用 Agent 时抛出。"""


@dataclass(frozen=True)
class AgentRegistration:
    """One published implementation and an immutable definition snapshot."""

    ref: AgentRegistrationRef
    definition: AgentDefinition
    implementation: BaseAgent


def _definition(agent: BaseAgent) -> AgentDefinition:
    fields = set(AgentDefinition.model_fields) - {"agent_id"}
    return AgentDefinition(
        agent_id=str(agent.profile.agent_id or agent.profile.agent_name),
        **{key: getattr(agent.profile, key) for key in fields},
    )


class AgentRegistry:
    """注册并按领域、名称、能力解析 Agent。"""

    def __init__(self) -> None:
        self._registry_id = uuid4().hex
        self._lock = RLock()
        self._registrations: dict[str, AgentRegistration] = {}
        self._defaults: dict[tuple[str, str], str] = {}
        self._definitions: dict[tuple[str, str], AgentDefinition] = {}
        self._generations: dict[str, int] = {}
        self._owners: dict[str, tuple[str, str, str, str | None]] = {}
        self._disabled: set[str] = set()
        self._bound_agents: set[str] = set()
        self._instance_owners: dict[str, tuple[str, str, str]] = {}

    def register(self, agent: BaseAgent) -> None:
        """按规范化领域和名称登记 Agent，空标识不写入。"""
        self.register_instance(agent, make_default=True)

    def register_instance(
        self, agent: BaseAgent, *, instance_id: str | None = None,
        make_default: bool = False, expected_generation: int | None = None,
        _initial_plugin_stamp: bool = False,
        _publish_facts: Callable[[AgentRegistration], None] | None = None,
    ) -> AgentRegistrationRef:
        """Publish an instance; same object/declaration is idempotent, replacement fenced."""
        domain = (agent.profile.domain or "").strip().lower()
        name = (agent.profile.agent_name or "").strip().lower()
        if not domain or not name:
            raise ValueError("agent domain and agentName are required")
        definition = _definition(agent)
        key = (domain, name)
        with self._lock:
            instance_id = instance_id.strip() if instance_id is not None else self._defaults.get(key, f"{domain}:{name}")
            if not instance_id:
                raise ValueError("agent instanceId must not be blank")
            if make_default and key in self._defaults and self._defaults[key] != instance_id:
                raise ValueError("changing the default instance requires replacing its existing identity")
            previous = self._registrations.get(instance_id)
            generation = self._generations.get(instance_id, 0)
            instance_owner = (definition.agent_id, *key)
            if instance_id in self._instance_owners and self._instance_owners[instance_id] != instance_owner:
                raise ValueError("agent instance identity cannot be reassigned")
            if expected_generation is not None:
                if type(expected_generation) is not int or expected_generation < 0:
                    raise ValueError("agent expected generation must be a nonnegative integer")
                current_generation = previous.ref.generation if previous is not None else 0
                if expected_generation != current_generation:
                    raise ValueError("agent registration generation conflict")
            owner = (*key, definition.source, definition.plugin_id)
            old_owner = self._owners.get(definition.agent_id)
            stamping = (
                _initial_plugin_stamp and previous is not None and previous.implementation is agent
                and previous.ref.generation == 1 and old_owner == (*key, "native", None)
                and definition.source == "plugin" and bool(definition.plugin_id)
            )
            if old_owner is not None and old_owner != owner and not stamping:
                raise ValueError("agent registration owner cannot change")
            if previous is not None:
                old = previous.definition
                if old.agent_id != definition.agent_id or (old.domain.lower(), old.agent_name.lower()) != key:
                    raise ValueError("agent instance identity cannot be reassigned")
                if not stamping and (old.source, old.plugin_id) != (definition.source, definition.plugin_id):
                    raise ValueError("agent registration owner cannot change")
            # A logical ID must remain unambiguous for legacy scope/ID lookup.
            for other_id, other in self._registrations.items():
                if other_id != instance_id and other.implementation is agent:
                    raise ValueError("one implementation object cannot represent multiple Agent instances")
                if other_id != instance_id and other.definition.agent_id == definition.agent_id:
                    if (other.definition.domain.lower(), other.definition.agent_name.lower()) != key:
                        raise ValueError("agent logical ID is ambiguous")
                    if (other.definition.source, other.definition.plugin_id) != (definition.source, definition.plugin_id):
                        raise ValueError("agent registration owner cannot change")
            version_key = (definition.agent_id, definition.definition_version)
            if definition.definition_version is not None:
                existing = next((item for item in self._definitions.values()
                                 if (item.agent_id, item.definition_version) == version_key
                                 and (item.source, item.plugin_id) == (definition.source, definition.plugin_id)), None)
                if existing is not None and existing != definition:
                    raise ValueError("agent definition version conflicts with its published declaration")
            if previous is not None and previous.implementation is agent and previous.definition == definition:
                registration = previous
            else:
                ref = AgentRegistrationRef(
                    registryId=self._registry_id, instanceId=instance_id,
                    agentId=definition.agent_id, generation=generation + 1,
                    definitionDigest=definition.digest, definitionVersion=definition.definition_version,
                )
                registration = AgentRegistration(ref, definition, agent)
                # Reserve the number before publication. An uncertain store
                # write can leave an orphan fact, but its ref is never reused.
                self._generations[instance_id] = ref.generation
            if _publish_facts is not None:
                _publish_facts(registration)
            if registration is not previous:
                self._registrations[instance_id] = registration
                self._definitions[(definition.agent_id, definition.digest)] = definition
            if not agent.profile.enabled or any(
                item.ref.agent_id == definition.agent_id and not item.implementation.profile.enabled
                for item in self._registrations.values() if item is not registration
            ):
                self._disabled.add(definition.agent_id)
            # Preserve a direct legacy disable even when its only object is
            # being replaced. Re-registration is never an enable operation.
            if previous is not None and not previous.implementation.profile.enabled:
                self._disabled.add(definition.agent_id)
            if definition.agent_id in self._disabled:
                agent.profile.enabled = False
            self._owners[definition.agent_id] = owner
            self._instance_owners[instance_id] = instance_owner
            if make_default or key not in self._defaults:
                self._defaults[key] = instance_id
            return registration.ref

    def stamp_plugin(self, agent: BaseAgent, *, plugin_id: str, plugin_version: str, contribution_id: str) -> None:
        """Startup Pack assembly only; runtime registration cannot change owner."""
        with self._lock:
            ref = self.registration_for(agent)
            if ref.generation != 1 or ref.agent_id in self._bound_agents:
                raise ValueError("plugin provenance must be stamped during initial assembly")
            original = agent.profile
            agent.profile = original.model_copy(update={
                "source": "plugin", "plugin_id": plugin_id,
                "plugin_version": plugin_version, "contribution_id": contribution_id,
            })
            try:
                self.register_instance(agent, instance_id=ref.instance_id, _initial_plugin_stamp=True)
            except Exception:
                agent.profile = original
                raise

    def is_enabled(self, agent_id: str) -> bool:
        with self._lock:
            return agent_id not in self._disabled and all(
                item.implementation.profile.enabled for item in self._registrations.values()
                if item.ref.agent_id == agent_id
            )

    def set_enabled(self, agent_id: str, *, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise ValueError("Agent enabled must be boolean")
        with self._lock:
            if agent_id not in self._owners:
                raise AgentNotFound("Agent definition is not registered")
            if enabled:
                self._disabled.discard(agent_id)
            else:
                self._disabled.add(agent_id)
            for item in self._registrations.values():
                if item.ref.agent_id == agent_id:
                    item.implementation.profile.enabled = enabled

    def registrations(self, *, allowed_agent_ids: Iterable[str] | None = None) -> tuple[AgentRegistration, ...]:
        allowed = set(allowed_agent_ids) if allowed_agent_ids is not None else None
        with self._lock:
            return tuple(item for item in self._registrations.values()
                         if allowed is None or item.ref.agent_id in allowed)

    def definitions(self) -> tuple[AgentDefinition, ...]:
        with self._lock:
            return tuple(self._definitions.values())

    def get_registration(
        self, ref: AgentRegistrationRef, *, allowed_agent_ids: Iterable[str] | None = None,
    ) -> AgentRegistration:
        """Read current facts without admitting an invocation or sealing provenance."""
        allowed = set(allowed_agent_ids) if allowed_agent_ids is not None else None
        with self._lock:
            item = self._registrations.get(ref.instance_id)
            if item is None or item.ref != ref or (allowed is not None and ref.agent_id not in allowed):
                raise AgentNotFound("agent registration is stale or outside the execution scope")
            return item

    def registration_for(self, agent: BaseAgent) -> AgentRegistrationRef:
        with self._lock:
            matches = [item for item in self._registrations.values() if item.implementation is agent]
            if len(matches) != 1 or matches[0].definition != _definition(agent):
                raise AgentNotFound("agent implementation has no exact current registration")
            return matches[0].ref

    def bind(self, agent: BaseAgent) -> AgentRegistrationRef:
        with self._lock:
            ref = self.registration_for(agent)
            self.resolve_registration(ref)
            return ref

    def resolve_registration(
        self, ref: AgentRegistrationRef, *, allowed_agent_ids: Iterable[str] | None = None,
    ) -> BaseAgent:
        with self._lock:
            item = self.get_registration(ref, allowed_agent_ids=allowed_agent_ids)
            if not self._is_eligible(item.implementation) or item.definition != _definition(item.implementation):
                raise AgentNotFound("agent registration is disabled or its declaration changed")
            self._bound_agents.add(ref.agent_id)
            return item.implementation

    def unregister_instance(self, ref: AgentRegistrationRef, *,
                            _withdraw_facts: Callable[[], None] | None = None) -> None:
        with self._lock:
            self.get_registration(ref)
            if not self.is_enabled(ref.agent_id):
                self._disabled.add(ref.agent_id)
            if _withdraw_facts is not None:
                _withdraw_facts()
            self._registrations.pop(ref.instance_id)
            for key, instance_id in list(self._defaults.items()):
                if instance_id == ref.instance_id:
                    self._defaults.pop(key)

    def resolve(
        self,
        domain: str,
        agent_name: Optional[str] = None,
        capability: Optional[str] = None,
        *,
        allowed_agent_ids: Iterable[str] | None = None,
    ) -> BaseAgent:
        """在可见范围内优先按名称、再按能力解析 Agent。"""
        normalized_domain = (domain or "").strip().lower()
        normalized_name = (agent_name or "").strip().lower()
        normalized_capability = (capability or "").strip().lower()
        allowed = set(allowed_agent_ids) if allowed_agent_ids is not None else None
        agents = self._default_agents()
        if normalized_name:
            for candidate_domain in (normalized_domain, "general"):
                agent = agents.get((candidate_domain, normalized_name))
                if (
                    agent is not None
                    and self._is_eligible(agent, normalized_capability)
                    and (allowed is None or self.agent_id(agent) in allowed)
                ):
                    return agent
        if normalized_capability:
            for candidate_domain in ((normalized_domain, "general") if normalized_domain != "general" else ("general",)):
                for (agent_domain, _), agent in agents.items():
                    if agent_domain != candidate_domain:
                        continue
                    if allowed is not None and self.agent_id(agent) not in allowed:
                        continue
                    if self._is_eligible(agent, normalized_capability):
                        return agent
        raise AgentNotFound(
            f"agent not registered: domain={domain}, agentName={agent_name}, capability={capability}"
        )

    def resolve_by_id(
        self,
        agent_id: str,
        *,
        allowed_agent_ids: Iterable[str] | None = None,
    ) -> BaseAgent:
        """按稳定 Agent 标识解析实例，并保持冻结 scope 的访问限制。"""
        normalized_id = str(agent_id).strip()
        allowed = set(allowed_agent_ids) if allowed_agent_ids is not None else None
        if allowed is not None and normalized_id not in allowed:
            raise AgentNotFound(f"agent is outside the execution scope: {normalized_id}")
        for agent in self.all():
            if self.agent_id(agent) == normalized_id and self._is_eligible(agent):
                return agent
        raise AgentNotFound(f"agent id is not registered: {normalized_id}")

    def all(self) -> Iterable[BaseAgent]:
        """按登记顺序返回默认逻辑 Agent 快照。"""
        return tuple(self._default_agents().values())

    def _default_agents(self) -> dict[tuple[str, str], BaseAgent]:
        with self._lock:
            return {key: self._registrations[instance_id].implementation
                    for key, instance_id in self._defaults.items()}

    def _is_eligible(self, agent: BaseAgent, capability: str = "") -> bool:
        """Names are preferences; disabled or capability-incompatible Agents cannot enter."""
        return agent.profile.enabled and self.is_enabled(str(self.agent_id(agent))) and (
            not capability
            or capability in {item.strip().lower() for item in agent.profile.capabilities}
        )

    @staticmethod
    def agent_id(agent: BaseAgent) -> LogicalAgentId:
        """优先返回显式 Agent 标识，缺失时回退到名称。"""
        return LogicalAgentId(str(agent.profile.agent_id or agent.profile.agent_name).strip())

    def scoped(self, agent_ids: Iterable[str]) -> "ScopedAgentRegistry":
        """创建仅包含指定标识的只读运行范围视图。"""
        return ScopedAgentRegistry(self, tuple(agent_ids))


class ScopedAgentRegistry:
    """单个 run 的冻结 Agent 可见性视图。"""

    def __init__(self, registry: AgentRegistry, agent_ids: tuple[str, ...]) -> None:
        self._registry = registry
        self._agent_ids = frozenset(agent_ids)

    def all(self) -> Iterable[BaseAgent]:
        """返回底层注册表中属于当前运行范围的 Agent。"""
        return tuple(agent for agent in self._registry.all() if self._registry.agent_id(agent) in self._agent_ids)

    def agent_id(self, agent: BaseAgent) -> str:
        """委托底层注册表获得稳定标识，不扩大当前可见范围。"""
        return self._registry.agent_id(agent)

    def resolve(self, domain: str, agent_name: Optional[str] = None, capability: Optional[str] = None) -> BaseAgent:
        """仅从冻结范围内解析 Agent；越界候选与缺失候选都明确失败。"""
        return self._registry.resolve(domain, agent_name, capability, allowed_agent_ids=self._agent_ids)

    def resolve_by_id(self, agent_id: str) -> BaseAgent:
        """只按当前冻结 scope 内的稳定 Agent 标识解析实例。"""
        return self._registry.resolve_by_id(agent_id, allowed_agent_ids=self._agent_ids)

    def get_registration(self, ref: AgentRegistrationRef) -> AgentRegistration:
        return self._registry.get_registration(ref, allowed_agent_ids=self._agent_ids)

    def registration_for(self, agent: BaseAgent) -> AgentRegistrationRef:
        ref = self._registry.registration_for(agent)
        if ref.agent_id not in self._agent_ids:
            raise AgentNotFound("agent registration is outside the execution scope")
        return ref

    def bind(self, agent: BaseAgent) -> AgentRegistrationRef:
        ref = self.registration_for(agent)
        self.resolve_registration(ref)
        return ref

    def resolve_registration(self, ref: AgentRegistrationRef) -> BaseAgent:
        return self._registry.resolve_registration(ref, allowed_agent_ids=self._agent_ids)

    def registrations(self) -> tuple[AgentRegistration, ...]:
        return self._registry.registrations(allowed_agent_ids=self._agent_ids)

    def is_enabled(self, agent_id: str) -> bool:
        return agent_id in self._agent_ids and self._registry.is_enabled(agent_id)
