"""端边云两层调度服务：先选 Agent，再放置节点，最后租约。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from contracts.resource import AgentProfile, BindingRequirement, ExecutionBinding, NodeProfile, ResourceType


@dataclass(frozen=True)
class TwoLayerPlacement:
    """两层调度的一次决策结果：选定 Agent 与目标节点。"""

    agent: AgentProfile
    node: NodeProfile
    effective_requirements: dict[str, object]
    agent_score: float
    node_score: float
    pair_score: float

from ..resource.agent_service import AgentService
from ..resource.node_service import NodeService
from .agent_selection import agent_eligible, agent_score
from .leases import InMemoryLeaseCoordinator, LeaseCoordinator
from .models import CandidateDecision, FilterReason, ReadyNodeSchedulingResult
from .node_placement import node_eligible, node_score


def _reliability_from_failures(consecutive_failures: int) -> float:
    return 1.0 / (1.0 + consecutive_failures)


_PRIVACY_RANK = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}


def _stricter_privacy(left: str | None, right: str | None) -> str | None:
    values = [value for value in (left, right) if value]
    if not values:
        return None
    return max(values, key=lambda item: _PRIVACY_RANK.get(item, -1))


def _merged(values: list[str] | tuple[str, ...], more: list[str] | tuple[str, ...]) -> list[str]:
    return list(dict.fromkeys([*values, *more]))


class TwoLayerSchedulerService:
    """组合节点放置与 Agent 选择，作为统一资源调度的替代入口。"""

    def __init__(
        self,
        node_service: NodeService | None = None,
        agent_service: AgentService | None = None,
        *,
        coordinator: LeaseCoordinator | None = None,
        lease_ttl: timedelta = timedelta(seconds=60),
    ) -> None:
        self.node_service = node_service or NodeService()
        self.agent_service = agent_service or AgentService()
        self.coordinator = coordinator or InMemoryLeaseCoordinator()
        self.lease_ttl = lease_ttl

    def select_agent(
        self, *, capabilities: list[str], only_idle: bool = True
    ) -> AgentProfile | None:
        """按能力标签 + 忙闲 + 历史成功率选择最优 Agent。"""
        candidates = self.agent_service.candidates(capabilities=capabilities, only_idle=only_idle)
        return candidates[0][0] if candidates else None

    def place_node(
        self,
        *,
        min_gpu_memory_mb: int = 0,
        min_privacy_level: str | None = None,
        node_types: list[str] | None = None,
        allowed_node_ids: list[str] | None = None,
        required_model_ids: list[str] | None = None,
        now: datetime | None = None,
    ) -> NodeProfile | None:
        """硬约束过滤 + 软评分选出最优节点。"""
        best: tuple[float, NodeProfile] | None = None
        allowed = set(allowed_node_ids or [])
        required_models = set(required_model_ids or [])
        for profile in self.node_service.profiles():
            if allowed and profile.node_id not in allowed:
                continue
            if node_types and profile.node_type.value not in node_types:
                continue
            if required_models and not required_models.issubset(set(profile.model_ids)):
                continue
            snapshot = self.node_service.snapshot(profile.node_id).snapshot
            health = self.node_service.health(profile.node_id, now=now)
            if not node_eligible(
                profile,
                health_status=health.status,
                min_gpu_memory_mb=min_gpu_memory_mb,
                min_privacy_level=min_privacy_level,
            ):
                continue
            reliability = _reliability_from_failures(health.consecutive_failures)
            score = node_score(profile, snapshot, reliability=reliability)
            if best is None or score > best[0]:
                best = (score, profile)
        return best[1] if best else None

    def schedule(
        self,
        *,
        capabilities: list[str],
        allowed_agent_ids: list[str] | None = None,
        allowed_node_ids: list[str] | None = None,
        required_model_ids: list[str] | None = None,
        min_gpu_memory_mb: int = 0,
        min_privacy_level: str | None = None,
        node_types: list[str] | None = None,
        only_idle: bool = True,
        now: datetime | None = None,
    ) -> TwoLayerPlacement | None:
        """两层调度：枚举合法 Agent/Node 组合并返回最高分配对。"""
        pairs: list[tuple[float, str, str, TwoLayerPlacement]] = []
        allowed_agents = set(allowed_agent_ids or [])
        allowed_nodes = set(allowed_node_ids or [])
        for agent, agent_snapshot in self.agent_service.candidates(
            capabilities=capabilities,
            only_idle=only_idle,
        ):
            if allowed_agents and agent.agent_id not in allowed_agents:
                continue
            effective_models = _merged(required_model_ids or [], agent.required_model_ids)
            effective_gpu = max(min_gpu_memory_mb, agent.required_gpu_memory_mb)
            effective_privacy = _stricter_privacy(min_privacy_level, agent.min_privacy_level)
            allowed = set(agent.allowed_node_ids)
            for node in self.node_service.profiles():
                if allowed_nodes and node.node_id not in allowed_nodes:
                    continue
                if allowed and node.node_id not in allowed:
                    continue
                if node_types and node.node_type.value not in node_types:
                    continue
                if effective_models and not set(effective_models).issubset(node.model_ids):
                    continue
                node_snapshot = self.node_service.snapshot(node.node_id).snapshot
                health = self.node_service.health(node.node_id, now=now)
                if not node_eligible(
                    node,
                    health_status=health.status,
                    min_gpu_memory_mb=effective_gpu,
                    min_privacy_level=effective_privacy,
                ):
                    continue
                reliability = _reliability_from_failures(health.consecutive_failures)
                a_score = agent_score(agent_snapshot.snapshot)
                n_score = node_score(node, node_snapshot, reliability=reliability)
                pair_score = round((0.55 * a_score) + (0.45 * n_score), 9)
                placement = TwoLayerPlacement(
                    agent=agent,
                    node=node,
                    effective_requirements={
                        "requiredModelIds": effective_models,
                        "minGpuMemoryMb": effective_gpu,
                        "minPrivacyLevel": effective_privacy,
                    },
                    agent_score=a_score,
                    node_score=n_score,
                    pair_score=pair_score,
                )
                pairs.append((pair_score, agent.agent_id, node.node_id, placement))
        if not pairs:
            return None
        pairs.sort(key=lambda item: (-item[0], item[1], item[2]))
        return pairs[0][3]

    def schedule_ready(
        self,
        *,
        run_id: str,
        step_id: str,
        attempt_id: str,
        requirement: BindingRequirement,
        now: datetime | None = None,
    ) -> ReadyNodeSchedulingResult:
        """Allocate a ready step from the authoritative Agent/Node ledgers."""
        current = now or datetime.now(timezone.utc)
        node_types = [
            item.value for item in requirement.resource_types
            if item.value in {"worker", "model", "embedding", "tool", "mcp"}
        ]
        preferred_agent = _non_empty_string(requirement.preferences.get("agentId"))
        preferred_node = _non_empty_string(requirement.preferences.get("nodeId"))
        placement = self.schedule(
            capabilities=list(requirement.required_capabilities),
            allowed_agent_ids=(
                [preferred_agent]
                if preferred_agent
                else None
            ),
            allowed_node_ids=(
                [preferred_node]
                if preferred_node
                else None
            ),
            required_model_ids=list(requirement.required_model_ids),
            min_gpu_memory_mb=requirement.min_gpu_memory_mb,
            min_privacy_level=requirement.privacy_level,
            node_types=node_types or None,
            only_idle=True,
            now=current,
        )
        candidates: list[CandidateDecision] = []
        if placement is None:
            return ReadyNodeSchedulingResult(
                status="queued",
                candidates=candidates,
                reason="NO_ELIGIBLE_RESOURCE",
            )
        if preferred_agent and placement.agent.agent_id != preferred_agent:
            candidates.append(CandidateDecision(
                resourceId=placement.node.node_id,
                accepted=False,
                reasons=[FilterReason.NOT_ALLOWED],
                score=placement.pair_score,
            ))
            return ReadyNodeSchedulingResult(
                status="queued",
                candidates=candidates,
                reason="NO_ELIGIBLE_RESOURCE",
            )
        if preferred_node and placement.node.node_id != preferred_node:
            candidates.append(CandidateDecision(
                resourceId=placement.node.node_id,
                accepted=False,
                reasons=[FilterReason.NOT_ALLOWED],
                score=placement.pair_score,
            ))
            return ReadyNodeSchedulingResult(
                status="queued",
                candidates=candidates,
                reason="NO_ELIGIBLE_RESOURCE",
            )
        if requirement.allowed_resource_ids and placement.agent.agent_id not in requirement.allowed_resource_ids:
            candidates.append(CandidateDecision(
                resourceId=placement.node.node_id,
                accepted=False,
                reasons=[FilterReason.NOT_ALLOWED],
                score=placement.pair_score,
            ))
            return ReadyNodeSchedulingResult(
                status="queued",
                candidates=candidates,
                reason="NO_ELIGIBLE_RESOURCE",
            )
        versioned = self.node_service.snapshot(placement.node.node_id)
        capacity = max(1, int(placement.agent.metadata.get("maxConcurrency", 1)))
        lease_id = f"lease:{run_id}:{step_id}:{attempt_id}:{placement.agent.agent_id}:{placement.node.node_id}"
        lease = self.coordinator.acquire(
            lease_id=lease_id,
            resource_id=placement.node.node_id,
            capacity=capacity,
            run_id=run_id,
            step_id=step_id,
            attempt_id=attempt_id,
            agent_id=placement.agent.agent_id,
            node_id=placement.node.node_id,
            slot_count=1,
            ttl=self.lease_ttl,
            now=current,
        )
        decision = CandidateDecision(
            resourceId=placement.node.node_id,
            accepted=True,
            reasons=[],
            score=placement.pair_score,
        )
        if lease is None:
            return ReadyNodeSchedulingResult(
                status="queued",
                candidates=[decision],
                reason="NO_CAPACITY",
            )
        binding = ExecutionBinding(
            bindingId=f"binding:{run_id}:{step_id}:{attempt_id}",
            runId=run_id,
            stepId=step_id,
            attemptId=attempt_id,
            resourceId=placement.node.node_id,
            resourceType=ResourceType.WORKER,
            snapshotVersion=versioned.version,
            metadata={
                "score": placement.pair_score,
                "agentId": placement.agent.agent_id,
                "nodeId": placement.node.node_id,
                "deploymentTier": placement.node.deployment_tier.value,
                "placementReasons": [
                    f"deploymentTier={placement.node.deployment_tier.value}",
                    f"nodeType={placement.node.node_type.value}",
                ],
                "scoreFactors": {
                    "agentScore": placement.agent_score,
                    "nodeScore": placement.node_score,
                },
                "effectiveRequirements": placement.effective_requirements,
            },
        )
        return ReadyNodeSchedulingResult(
            status="allocated",
            binding=binding,
            lease=lease,
            candidates=[decision],
        )

    def release(self, lease_id: str) -> bool:
        return self.coordinator.release(lease_id)


def _non_empty_string(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
