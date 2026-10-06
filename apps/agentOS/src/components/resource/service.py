"""资源平面：Node / Runtime / ModelEndpoint 的登记、观测与候选查询。

本服务是资源状态的唯一权威入口。它回答"系统现在拥有哪些真实可调用的
运行能力"，但不做调度决策——候选过滤、评分与租约授予由 ResourceBinder
完成。逻辑 Agent 角色不是资源，不在这里登记。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from typing import Literal

from contracts.capability import ModelFeatureSet
from contracts.resource import (
    HealthStatus,
    ModelDemand,
    ModelEndpointProfile,
    NodeHealthStatus,
    NodeProfile,
    NodeSnapshot,
    Placement,
    RuntimeProfile,
    RuntimeSnapshot,
    TrustLevel,
)

from .algorithms import health_score, is_runtime_available
from .crypto import ResourceSecretBox
from .health import ResourceHealthMonitor
from .models import (
    ModelEndpointCandidate,
    NodeHealth,
    RuntimeCandidate,
    RuntimeHealth,
    VersionedNodeSnapshot,
    VersionedRuntimeSnapshot,
)
from .node_health import NodeHealthMonitor, infer_load_status
from .node_store import InMemoryNodeStore, NodeStore
from .store import (
    InMemoryResourceStore,
    ResourceCredentialRecord,
    RuntimeStore,
    SQLiteResourceStore,
    StaleResourceObservation,
)


@dataclass(frozen=True)
class IssuedResourceCredential:
    """注册响应中一次性返回的 Runtime 密钥。"""

    resource_id: str
    credential_id: str
    owner_scope: str
    secret: str


@dataclass(frozen=True)
class IssuedNodeCredential:
    """远程节点登记响应中一次性返回的密钥。"""

    node_id: str
    credential_id: str
    owner_scope: str
    secret: str


class ResourcePlane:
    """以分层模型暴露可调度资源，并向 Binder 提供候选查询。"""

    def __init__(
        self,
        store: RuntimeStore | None = None,
        node_store: NodeStore | None = None,
        health_monitor: ResourceHealthMonitor | None = None,
        node_health_monitor: NodeHealthMonitor | None = None,
        *,
        heartbeat_timeout: timedelta = timedelta(seconds=60),
        credential_key: str | bytes | None = None,
    ) -> None:
        self.store = store or InMemoryResourceStore()
        self.node_store = node_store or InMemoryNodeStore()
        self.health_monitor = health_monitor or ResourceHealthMonitor(
            heartbeat_timeout=heartbeat_timeout
        )
        self.node_health_monitor = node_health_monitor or NodeHealthMonitor()
        self.secret_box = ResourceSecretBox(credential_key)

    # ------------------------------------------------------------------
    # Node 层：部署实体
    # ------------------------------------------------------------------

    def register_node(self, profile: NodeProfile, snapshot: NodeSnapshot) -> VersionedNodeSnapshot:
        """登记节点；重复的完全一致登记幂等返回。"""
        if profile.node_id != snapshot.node_id:
            raise ValueError("node profile and snapshot nodeId must match")
        try:
            existing = self.node_store.get_profile(profile.node_id)
        except KeyError:
            return self.node_store.register(profile, snapshot)
        if existing != profile:
            raise ValueError(f"node conflicts with existing profile: {profile.node_id}")
        return self.node_store.get_snapshot(profile.node_id)

    def ensure_node(
        self,
        node_id: str,
        *,
        placement: Placement = Placement.DEVICE,
        display_name: str = "",
        trust: TrustLevel = TrustLevel.HOST_TRUSTED,
        **profile_fields,
    ) -> NodeProfile:
        """幂等登记（或读取）节点；进程内引导路径专用。

        只允许更新引导自有的节点；远程登记（带凭据、无引导标记）的节点
        与引导声明冲突时必须显式失败，防止进程内代码静默改写外部身份。
        """
        metadata = dict(profile_fields.pop("metadata", None) or {})
        metadata.setdefault("managedBy", "bootstrap")
        profile = NodeProfile(
            nodeId=node_id,
            placement=placement,
            displayName=display_name,
            trust=trust,
            metadata=metadata,
            **profile_fields,
        )
        try:
            existing = self.node_store.get_profile(node_id)
        except KeyError:
            snapshot = NodeSnapshot(
                nodeId=node_id,
                healthStatus=NodeHealthStatus.ONLINE,
                lastHeartbeat=datetime.now(timezone.utc),
            )
            self.node_store.register(profile, snapshot)
            self.node_health_monitor.report(node_id, success=True)
            return profile
        if existing == profile:
            return existing
        if existing.metadata.get("managedBy") != "bootstrap":
            # Older local bootstrap records predate the ownership marker. Adopt
            # only an otherwise identical device profile without credentials.
            legacy_local = (
                existing.placement is Placement.DEVICE
                and existing.trust is TrustLevel.HOST_TRUSTED
                and existing.owner_scope is None
                and not existing.metadata
                and metadata == {"managedBy": "bootstrap"}
                and existing.model_copy(update={"metadata": metadata}) == profile
            )
            if legacy_local:
                try:
                    self.node_store.get_credential(node_id)
                except KeyError:
                    return self.node_store.update_profile(profile)
            raise ValueError(f"node conflicts with a non-bootstrap registration: {node_id}")
        return self.node_store.update_profile(profile)

    def register_remote_node(self, profile: NodeProfile, snapshot: NodeSnapshot) -> IssuedNodeCredential:
        """登记远程节点并生成只能在注册响应中读取一次的凭据。"""
        if profile.placement is Placement.DEVICE:
            raise ValueError("remote node must use a non-device placement")
        if not profile.owner_scope:
            raise ValueError("remote node ownerScope is required")
        secret = secrets.token_urlsafe(32)
        record = ResourceCredentialRecord(
            resource_id=profile.node_id,
            credential_id=f"nc_{uuid.uuid4().hex}",
            owner_scope=profile.owner_scope,
            secret_digest=hashlib.sha256(secret.encode("utf-8")).hexdigest(),
            encrypted_secret=self.secret_box.encrypt(secret),
            created_at=datetime.now(timezone.utc),
        )
        self.node_store.register_remote(profile, snapshot, record)
        return IssuedNodeCredential(
            node_id=profile.node_id,
            credential_id=record.credential_id,
            owner_scope=record.owner_scope,
            secret=secret,
        )

    def node(self, node_id: str) -> NodeProfile:
        return self.node_store.get_profile(node_id)

    def nodes(self) -> list[NodeProfile]:
        return self.node_store.list_profiles()

    def node_snapshot(self, node_id: str) -> VersionedNodeSnapshot:
        return self.node_store.get_snapshot(node_id)

    def set_node_enabled(self, node_id: str, *, enabled: bool) -> NodeProfile:
        profile = self.node_store.get_profile(node_id)
        return self.node_store.update_profile(
            profile.model_copy(update={"enabled": enabled})
        )

    def node_health(self, node_id: str, *, now: datetime | None = None) -> NodeHealth:
        live = self.node_health_monitor.health(node_id, now=now)
        if live.last_heartbeat is not None:
            return live
        snapshot = self.node_store.get_snapshot(node_id).snapshot
        if snapshot.last_heartbeat is None:
            return live
        current = now if now is not None else datetime.now(timezone.utc)
        age = current.astimezone(timezone.utc) - snapshot.last_heartbeat.astimezone(timezone.utc)
        if age > self.node_health_monitor.offline_threshold:
            status = NodeHealthStatus.OFFLINE
        elif age > self.node_health_monitor.stale_threshold:
            status = NodeHealthStatus.STALE
        else:
            status = snapshot.health_status
        return NodeHealth(
            node_id=node_id,
            status=status,
            last_heartbeat=snapshot.last_heartbeat,
            consecutive_failures=snapshot.consecutive_failures,
        )

    def observe_node(
        self,
        node_id: str,
        *,
        observation_sequence: int,
        cpu_utilization: float = 0.0,
        gpu_utilization: float = 0.0,
        available_memory_mb: int = 0,
        queued_tasks: int = 0,
        latency_ms: float | None = None,
        observed_at: datetime | None = None,
        success: bool = True,
    ) -> NodeHealth:
        """接收一次已签名的远程节点观测并持久化快照与健康。"""
        self.node_store.get_profile(node_id)
        current = self.node_store.get_snapshot(node_id)
        if observation_sequence <= current.snapshot.observation_sequence:
            raise StaleResourceObservation(
                f"stale observation for {node_id}: "
                f"received {observation_sequence}, "
                f"current {current.snapshot.observation_sequence}"
            )
        timestamp = observed_at if observed_at is not None else datetime.now(timezone.utc)
        load = max(cpu_utilization, gpu_utilization)
        consecutive_failures = 0 if success else current.snapshot.consecutive_failures + 1
        snapshot = current.snapshot.model_copy(update={
            "observation_sequence": observation_sequence,
            "observed_at": timestamp,
            "cpu_utilization": cpu_utilization,
            "gpu_utilization": gpu_utilization,
            "available_memory_mb": available_memory_mb,
            "queued_tasks": queued_tasks,
            "latency_ms": latency_ms,
            "health_status": infer_load_status(queued_tasks, load),
            "last_heartbeat": timestamp,
            "consecutive_failures": consecutive_failures,
        })
        self.node_store.update_snapshot(snapshot, expected_version=current.version)
        return self.node_health_monitor.report(
            node_id,
            observed_at=timestamp,
            queued_tasks=queued_tasks,
            utilization=load,
            success=success,
        )

    def heartbeat_node(
        self,
        node_id: str,
        *,
        cpu_utilization: float = 0.0,
        gpu_utilization: float = 0.0,
        available_memory_mb: int = 0,
        queued_tasks: int = 0,
        latency_ms: float | None = None,
        success: bool = True,
        observed_at: datetime | None = None,
    ) -> NodeHealth:
        """进程内节点心跳：刷新快照动态字段与健康投影。"""
        timestamp = observed_at if observed_at is not None else datetime.now(timezone.utc)
        current = self.node_store.get_snapshot(node_id)
        load = max(cpu_utilization, gpu_utilization)
        consecutive_failures = 0 if success else current.snapshot.consecutive_failures + 1
        snapshot = current.snapshot.model_copy(update={
            "cpu_utilization": cpu_utilization,
            "gpu_utilization": gpu_utilization,
            "available_memory_mb": available_memory_mb,
            "queued_tasks": queued_tasks,
            "latency_ms": latency_ms,
            "health_status": infer_load_status(queued_tasks, load),
            "last_heartbeat": timestamp,
            "observed_at": timestamp,
            "observation_sequence": current.snapshot.observation_sequence + 1,
            "consecutive_failures": consecutive_failures,
        })
        self.node_store.update_snapshot(snapshot, expected_version=current.version)
        return self.node_health_monitor.report(
            node_id,
            observed_at=timestamp,
            queued_tasks=queued_tasks,
            utilization=load,
            success=success,
        )

    def node_credential(self, node_id: str) -> ResourceCredentialRecord:
        self.node_store.get_profile(node_id)
        return self.node_store.get_credential(node_id)

    def node_credential_hmac_key(self, node_id: str, credential_id: str) -> bytes:
        record = self.node_credential(node_id)
        if record.credential_id != credential_id:
            raise ValueError("node credential is invalid")
        secret = self.secret_box.decrypt(record.encrypted_secret)
        return hashlib.sha256(secret.encode("utf-8")).digest()

    def verify_node_credential(
        self, node_id: str, credential_id: str, secret: str
    ) -> ResourceCredentialRecord:
        try:
            profile = self.node_store.get_profile(node_id)
            record = self.node_store.get_credential(node_id)
        except KeyError as error:
            raise ValueError("node credential not found") from error
        expected_digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        if (
            record.credential_id != credential_id
            or record.owner_scope != profile.owner_scope
            or not hmac.compare_digest(record.secret_digest, expected_digest)
        ):
            raise ValueError("node credential is invalid")
        return record

    def consume_node_nonce(
        self,
        node_id: str,
        nonce: str,
        expires_at: datetime,
        *,
        now: datetime | None = None,
    ) -> bool:
        self.node_store.get_profile(node_id)
        current = now or datetime.now(timezone.utc)
        return self.node_store.consume_nonce(node_id, nonce, expires_at, now=current)

    # ------------------------------------------------------------------
    # Runtime 层：承载实体（执行后端 / 模型服务 / 工具服务）
    # ------------------------------------------------------------------

    def register_runtime(
        self, profile: RuntimeProfile, snapshot: RuntimeSnapshot | None = None
    ) -> VersionedRuntimeSnapshot:
        """登记或刷新进程内引导的 Runtime；带凭据的远程登记不允许走此路径。

        引导路径（本进程拥有该 Runtime 的真实存活信号）允许更新能力集等
        画像字段；capacity 变化会按已占用量重新缩放松照槽位。
        """
        self._validate_runtime_host(profile)
        initial = snapshot or RuntimeSnapshot(
            runtimeId=profile.runtime_id,
            availableSlots=profile.capacity,
            utilization=0.0,
            healthStatus=HealthStatus.UNKNOWN,
        )
        if profile.runtime_id != initial.runtime_id:
            raise ValueError("profile and snapshot runtime_id must match")
        try:
            existing = self.store.get_profile(profile.runtime_id)
        except KeyError:
            return self.store.register(profile, initial)
        if existing == profile:
            return self.store.get_snapshot(profile.runtime_id)
        if not self._is_bootstrap_owned(existing):
            raise ValueError(
                f"runtime conflicts with credential-protected registration: {profile.runtime_id}"
            )
        if profile.capacity != existing.capacity:
            versioned = self.store.update_capacity(
                profile.runtime_id, profile.capacity, expected_capacity=existing.capacity
            )
            if existing != profile.model_copy(update={"capacity": profile.capacity}):
                self.store.update_profile(profile)
            return versioned
        self.store.update_profile(profile)
        return self.store.get_snapshot(profile.runtime_id)

    def register_remote_runtime(
        self,
        profile: RuntimeProfile,
        snapshot: RuntimeSnapshot,
        *,
        credential_id: str | None = None,
        secret: str | None = None,
    ) -> IssuedResourceCredential:
        """登记远程 Runtime 并生成只能在注册响应中读取一次的凭据。"""
        if profile.endpoint is None or profile.endpoint.protocol == "local":
            raise ValueError("remote runtime requires a callable execution endpoint")
        if not profile.owner_scope:
            raise ValueError("remote runtime ownerScope is required")
        self._validate_runtime_host(profile)
        if (credential_id is None) != (secret is None):
            raise ValueError("credential_id and secret must be supplied together")
        credential_id = credential_id.strip() if credential_id is not None else f"rc_{uuid.uuid4().hex}"
        secret = secret.strip() if secret is not None else secrets.token_urlsafe(32)
        if not credential_id or not secret:
            raise ValueError("remote credential_id and secret must not be empty")
        record = ResourceCredentialRecord(
            resource_id=profile.runtime_id,
            credential_id=credential_id,
            owner_scope=profile.owner_scope,
            secret_digest=hashlib.sha256(secret.encode("utf-8")).hexdigest(),
            encrypted_secret=self.secret_box.encrypt(secret),
            created_at=datetime.now(timezone.utc),
        )
        self.store.register_remote(profile, snapshot, record)
        return IssuedResourceCredential(
            resource_id=profile.runtime_id,
            credential_id=record.credential_id,
            owner_scope=record.owner_scope,
            secret=secret,
        )

    def _validate_runtime_host(self, profile: RuntimeProfile) -> None:
        node = self.node_store.get_profile(profile.node_id)
        if node.placement is not profile.placement:
            raise ValueError(
                f"runtime placement {profile.placement.value} must match host node "
                f"{node.node_id} placement {node.placement.value}"
            )
        if profile.trust.rank > node.trust.rank:
            raise ValueError(
                f"runtime trust {profile.trust.value} exceeds host node "
                f"{node.node_id} trust {node.trust.value}"
            )
        if not node.enabled:
            raise ValueError(f"host node is disabled: {node.node_id}")

    def _is_bootstrap_owned(self, existing: RuntimeProfile) -> bool:
        """引导路径可更新无凭据 Runtime，或显式标记为引导管理的 Runtime。

        远程 API 登记的 Runtime（有凭据且非引导标记）只能通过显式更新
        路径修改，防止进程内代码静默改写外部注册身份。
        """
        if existing.metadata.get("managedBy") == "bootstrap":
            return True
        return not self._has_runtime_credential(existing.runtime_id)

    def _has_runtime_credential(self, runtime_id: str) -> bool:
        try:
            self.store.get_credential(runtime_id)
        except KeyError:
            return False
        return True

    def runtime(self, runtime_id: str) -> RuntimeProfile:
        return self.store.get_profile(runtime_id)

    def runtimes(self) -> list[RuntimeProfile]:
        return self.store.list_profiles()

    def runtime_snapshot(self, runtime_id: str) -> VersionedRuntimeSnapshot:
        return self.store.get_snapshot(runtime_id)

    def set_runtime_enabled(self, runtime_id: str, *, enabled: bool) -> RuntimeProfile:
        profile = self.store.get_profile(runtime_id)
        return self.store.update_profile(profile.model_copy(update={"enabled": enabled}))

    def update_runtime_capacity(
        self, runtime_id: str, capacity: int, *, expected_capacity: int
    ) -> VersionedRuntimeSnapshot:
        return self.store.update_capacity(runtime_id, capacity, expected_capacity=expected_capacity)

    def heartbeat_runtime(
        self,
        runtime_id: str,
        *,
        received_at: datetime | None = None,
        source: Literal["local", "external"] = "local",
    ) -> RuntimeHealth:
        """记录 Runtime 存活信号；带端点的远程 Runtime 必须由外部上报。"""
        profile = self.store.get_profile(runtime_id)
        if profile.endpoint is not None and source != "external":
            raise ValueError("remote runtime heartbeat must come from an external heartbeat")
        return self.health_monitor.heartbeat(runtime_id, received_at=received_at)

    def observe_execution(
        self,
        runtime_id: str,
        *,
        success: bool,
        latency_ms: float,
        observed_at: datetime | None = None,
    ) -> RuntimeHealth:
        """记录一次执行结果：健康 EMA 与快照时延/可靠性同步更新。

        执行结果是执行链路自己的真实信号，不要求远端层级；利用率与槽位
        仍归调度器记账，这里不做任何推算。
        """
        self.store.get_profile(runtime_id)
        health = self.health_monitor.observe(
            runtime_id, success=success, latency_ms=latency_ms, observed_at=observed_at
        )
        timestamp = observed_at or datetime.now(timezone.utc)
        for _ in range(3):
            current = self.store.get_snapshot(runtime_id)
            # model_copy(update=) 只认字段名，不认别名；别名键会被静默忽略。
            updated = current.snapshot.model_copy(update={
                "observed_at": timestamp,
                "observation_sequence": current.snapshot.observation_sequence + 1,
                "latency_ms": latency_ms,
                "reliability": health.reliability,
                "health_status": (
                    HealthStatus.ONLINE if success else current.snapshot.health_status
                ),
            })
            try:
                self.store.update_snapshot(updated, expected_version=current.version)
                break
            except StaleResourceObservation:
                raise
            except Exception:
                # 并发完成回写时以最新版本为基准重放一次快照合并。
                continue
        return health

    def observe_remote_runtime(
        self,
        runtime_id: str,
        *,
        available_slots: int,
        utilization: float,
        latency_ms: float | None = None,
        observed_at: datetime | None = None,
        observation_sequence: int = 0,
    ) -> RuntimeHealth:
        """接收远程 Runtime 的一次完整观测，并同步快照与存活信号。"""
        profile = self.store.get_profile(runtime_id)
        if profile.endpoint is None:
            raise ValueError("remote observation requires an endpoint-attached runtime")
        current = self.store.get_snapshot(runtime_id)
        if observation_sequence <= current.snapshot.observation_sequence:
            raise StaleResourceObservation(
                f"stale observation for {runtime_id}: "
                f"received {observation_sequence}, "
                f"current {current.snapshot.observation_sequence}"
            )
        timestamp = observed_at or datetime.now(timezone.utc)
        updated = RuntimeSnapshot(
            runtimeId=runtime_id,
            observationSequence=observation_sequence,
            observedAt=timestamp,
            availableSlots=available_slots,
            utilization=utilization,
            healthStatus=HealthStatus.ONLINE,
            latencyMs=latency_ms,
        )
        self.store.update_snapshot(updated, expected_version=current.version)
        if latency_ms is None:
            return self.health_monitor.heartbeat(runtime_id, received_at=timestamp)
        return self.health_monitor.observe(
            runtime_id, success=True, latency_ms=latency_ms, observed_at=timestamp
        )

    def set_runtime_health(self, runtime_id: str, *, healthy: bool) -> RuntimeHealth:
        self.store.get_profile(runtime_id)
        return self.health_monitor.set_health(runtime_id, healthy=healthy)

    def runtime_candidates(
        self,
        required_capabilities: list[str] | tuple[str, ...] | set[str],
        *,
        labels: dict[str, str] | None = None,
        now: datetime | None = None,
    ) -> list[RuntimeCandidate]:
        """返回具备所需能力、健康且仍有槽位的稳定排序候选集（不含策略约束）。"""
        candidates: list[RuntimeCandidate] = []
        for profile in self.store.list_profiles():
            versioned = self.store.get_snapshot(profile.runtime_id)
            health = self.health_monitor.health(profile.runtime_id, now=now)
            if not is_runtime_available(
                profile, versioned.snapshot, health, required_capabilities, labels
            ):
                continue
            candidates.append(
                RuntimeCandidate(
                    profile=profile,
                    snapshot=versioned,
                    health=health,
                    score=health_score(health, versioned.snapshot.utilization),
                )
            )
        return sorted(
            candidates, key=lambda candidate: (-candidate.score, candidate.profile.runtime_id)
        )

    # ------------------------------------------------------------------
    # Runtime 凭据：签名的远程执行与观测
    # ------------------------------------------------------------------

    def issue_runtime_credential(self, runtime_id: str) -> IssuedResourceCredential:
        profile = self.store.get_profile(runtime_id)
        if profile.endpoint is None or profile.endpoint.protocol == "local":
            raise ValueError("runtime credentials require a remote endpoint")
        if not profile.owner_scope:
            raise ValueError("remote runtime ownerScope is required")
        return self._new_runtime_credential(profile)

    def rotate_runtime_credential(self, runtime_id: str) -> IssuedResourceCredential:
        profile = self.store.get_profile(runtime_id)
        if profile.endpoint is None or profile.endpoint.protocol == "local":
            raise ValueError("runtime credentials require a remote endpoint")
        if not profile.owner_scope:
            raise ValueError("remote runtime ownerScope is required")
        issued = self._new_runtime_credential_for_rotation(profile)
        return issued

    def _new_runtime_credential(self, profile: RuntimeProfile) -> IssuedResourceCredential:
        secret = secrets.token_urlsafe(32)
        record = ResourceCredentialRecord(
            resource_id=profile.runtime_id,
            credential_id=f"rc_{uuid.uuid4().hex}",
            owner_scope=profile.owner_scope or "",
            secret_digest=hashlib.sha256(secret.encode("utf-8")).hexdigest(),
            encrypted_secret=self.secret_box.encrypt(secret),
            created_at=datetime.now(timezone.utc),
        )
        self.store.save_credential(record)
        return IssuedResourceCredential(
            resource_id=profile.runtime_id,
            credential_id=record.credential_id,
            owner_scope=record.owner_scope,
            secret=secret,
        )

    def _new_runtime_credential_for_rotation(self, profile: RuntimeProfile) -> IssuedResourceCredential:
        secret = secrets.token_urlsafe(32)
        record = ResourceCredentialRecord(
            resource_id=profile.runtime_id,
            credential_id=f"rc_{uuid.uuid4().hex}",
            owner_scope=profile.owner_scope or "",
            secret_digest=hashlib.sha256(secret.encode("utf-8")).hexdigest(),
            encrypted_secret=self.secret_box.encrypt(secret),
            created_at=datetime.now(timezone.utc),
        )
        self.store.rotate_credential(record)
        return IssuedResourceCredential(
            resource_id=profile.runtime_id,
            credential_id=record.credential_id,
            owner_scope=record.owner_scope,
            secret=secret,
        )

    def verify_runtime_credential(
        self, runtime_id: str, credential_id: str, secret: str
    ) -> ResourceCredentialRecord:
        try:
            profile = self.store.get_profile(runtime_id)
            record = self.store.get_credential(runtime_id)
        except KeyError as error:
            raise ValueError("resource credential not found") from error
        expected_digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        if (
            record.credential_id != credential_id
            or record.owner_scope != profile.owner_scope
            or not hmac.compare_digest(record.secret_digest, expected_digest)
        ):
            raise ValueError("resource credential is invalid")
        return record

    def runtime_credential(self, runtime_id: str) -> ResourceCredentialRecord:
        self.store.get_profile(runtime_id)
        return self.store.get_credential(runtime_id)

    def runtime_credential_hmac_key(self, runtime_id: str, credential_id: str) -> bytes:
        record = self.runtime_credential(runtime_id)
        if record.credential_id != credential_id:
            raise ValueError("resource credential is invalid")
        secret = self.secret_box.decrypt(record.encrypted_secret)
        return hashlib.sha256(secret.encode("utf-8")).digest()

    def current_signing_credential(self, runtime_id: str) -> tuple[str, str]:
        """Return the current credential for an outbound resource request.

        This is deliberately read on every execution rather than copied into an
        Adapter at construction time, so credential rotation takes effect on the
        next request.  The plaintext exists only across this internal signing
        seam and is never included in a profile or response model.
        """
        record = self.runtime_credential(runtime_id)
        return record.credential_id, self.secret_box.decrypt(record.encrypted_secret)

    def current_signing_credential_or_none(self, runtime_id: str) -> tuple[str | None, str | None]:
        """引导路径的容错版凭据读取；未登记凭据时返回 ``(None, None)``。"""
        try:
            credential_id, secret = self.current_signing_credential(runtime_id)
        except KeyError:
            return None, None
        return credential_id, secret

    def consume_nonce(
        self,
        runtime_id: str,
        nonce: str,
        expires_at: datetime,
        *,
        now: datetime | None = None,
    ) -> bool:
        self.store.get_profile(runtime_id)
        current = now or datetime.now(timezone.utc)
        return self.store.consume_nonce(runtime_id, nonce, expires_at, now=current)

    # ------------------------------------------------------------------
    # ModelEndpoint 层：可绑定的模型路由
    # ------------------------------------------------------------------

    def upsert_model_endpoint(
        self, endpoint: ModelEndpointProfile
    ) -> tuple[ModelEndpointProfile, bool]:
        return self.store.upsert_model_endpoint(endpoint)

    def model_endpoint(self, endpoint_id: str) -> ModelEndpointProfile:
        return self.store.get_model_endpoint(endpoint_id)

    def model_endpoints(self) -> list[ModelEndpointProfile]:
        return self.store.list_model_endpoints()

    def delete_model_endpoint(self, endpoint_id: str) -> None:
        self.store.delete_model_endpoint(endpoint_id)

    def sync_model_endpoints(
        self, routes: list[dict], *, describe_model=None
    ) -> dict[str, int]:
        """把模型注册表的当前路由投影为模型端点目录。

        ``routes`` 的每一项至少包含 ``provider`` 与 ``model``；
        ``describe_model(provider, model)`` 可选，返回 ``ModelCapabilityEnvelope``
        用于补齐上下文窗口与特性声明。由本方法建立且不在 ``routes``
        中的端点会被移除（配置驱动收敛）。
        """
        keep: set[str] = set()
        replaced = 0
        removed = 0
        for route in routes:
            provider = str(route.get("provider") or "").strip()
            model = str(route.get("model") or "").strip()
            if not provider or not model:
                continue
            endpoint_id = f"model:{provider}/{model}"
            envelope = None
            if describe_model is not None:
                try:
                    envelope = describe_model(provider, model)
                except Exception:
                    envelope = None
            features: dict[str, bool] = {}
            context_window = None
            max_output = None
            placement = Placement.CLOUD
            if envelope is not None:
                context_window = envelope.context_window_tokens
                max_output = envelope.max_output_tokens
                feature_set = envelope.features
                features = {
                    key: value
                    for key, value in {
                        "json_schema": feature_set.json_schema,
                        "streaming": feature_set.streaming,
                        "tools": feature_set.tools,
                        "thinking": feature_set.thinking,
                        "prompt_caching": feature_set.prompt_caching,
                    }.items()
                    if value is not None
                }
                if provider.lower() in {"ollama", "vllm"}:
                    placement = Placement.DEVICE
            endpoint = ModelEndpointProfile(
                endpointId=endpoint_id,
                provider=provider,
                model=model,
                modelVersion=(str(route.get("version")) if route.get("version") else None),
                placement=placement,
                contextWindowTokens=context_window,
                maxOutputTokens=max_output,
                features=ModelFeatureSet.model_validate(features),
                metadata={"source": "model-registry-sync"},
            )
            _, changed = self.store.upsert_model_endpoint(endpoint)
            if changed:
                replaced += 1
            keep.add(endpoint_id)
        for existing in self.store.list_model_endpoints():
            if (
                existing.metadata.get("source") == "model-registry-sync"
                and existing.endpoint_id not in keep
            ):
                self.store.delete_model_endpoint(existing.endpoint_id)
                removed += 1
        return {"kept": len(keep), "replaced": replaced, "removed": removed}

    def model_candidates(
        self, demand: ModelDemand | None, *, now: datetime | None = None
    ) -> list[ModelEndpointCandidate]:
        """按模型需求返回可用端点候选；特征未声明的端点按不支持处理。"""
        demand = demand or ModelDemand()
        allowed = set(demand.allowed_endpoint_ids)
        excluded = set(demand.excluded_endpoint_ids)
        preferred = set(demand.preferred_model_ids)
        required_features = set(demand.required_features)
        candidates: list[ModelEndpointCandidate] = []
        for endpoint in self.store.list_model_endpoints():
            if not endpoint.enabled:
                continue
            if allowed and endpoint.endpoint_id not in allowed:
                continue
            if endpoint.endpoint_id in excluded:
                continue
            feature_map = endpoint.features.model_dump()
            if any(feature_map.get(feature) is not True for feature in required_features):
                continue
            if demand.min_context_tokens > 0 and (
                endpoint.context_window_tokens is None
                or endpoint.context_window_tokens < demand.min_context_tokens
            ):
                continue
            score = 1.0 + (
                0.1
                if endpoint.model in preferred
                or f"{endpoint.provider}/{endpoint.model}" in preferred
                else 0.0
            )
            candidates.append(ModelEndpointCandidate(endpoint=endpoint, score=score))
        return sorted(
            candidates,
            key=lambda item: (-item.score, item.endpoint.endpoint_id),
        )


__all__ = [
    "IssuedNodeCredential",
    "IssuedResourceCredential",
    "ResourcePlane",
    "SQLiteResourceStore",
]
