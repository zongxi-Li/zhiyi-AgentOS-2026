"""面向调度器的节点登记、心跳与候选查询服务。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import secrets
import uuid

from contracts.resource import DeploymentTier, NodeHealthStatus, NodeProfile, NodeSnapshot

from .crypto import ResourceSecretBox
from .models import NodeHealth, VersionedNodeSnapshot
from .node_health import NodeHealthMonitor, infer_load_status
from .node_store import InMemoryNodeStore, NodeStore
from .store import ResourceCredentialRecord, StaleResourceObservation


@dataclass(frozen=True)
class IssuedNodeCredential:
    """远程节点登记响应中一次性返回的密钥。"""

    node_id: str
    credential_id: str
    owner_scope: str
    secret: str

_PRIVACY_RANK = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}


def _privacy_rank(value: str) -> int:
    return _PRIVACY_RANK.get(value, -1)


class NodeService:
    """节点资源表的协调入口：登记、心跳、候选查询。"""

    def __init__(
        self,
        store: NodeStore | None = None,
        health_monitor: NodeHealthMonitor | None = None,
        *,
        credential_key: str | bytes | None = None,
    ) -> None:
        self.store = store or InMemoryNodeStore()
        self.health_monitor = health_monitor or NodeHealthMonitor()
        self.secret_box = ResourceSecretBox(credential_key)

    def register(self, profile: NodeProfile, snapshot: NodeSnapshot) -> VersionedNodeSnapshot:
        return self.store.register(profile, snapshot)

    def register_remote(
        self, profile: NodeProfile, snapshot: NodeSnapshot
    ) -> IssuedNodeCredential:
        """登记远程节点并生成只能在注册响应中读取一次的凭据。"""
        if profile.deployment_tier is DeploymentTier.LOCAL:
            raise ValueError("remote node must use a non-local deployment tier")
        if not profile.owner_scope:
            raise ValueError("remote node ownerScope is required")
        if profile.execution_endpoint is None or profile.execution_endpoint.protocol == "local":
            raise ValueError("remote node execution endpoint is required")
        secret = secrets.token_urlsafe(32)
        record = ResourceCredentialRecord(
            resource_id=profile.node_id,
            credential_id=f"nc_{uuid.uuid4().hex}",
            owner_scope=profile.owner_scope,
            secret_digest=hashlib.sha256(secret.encode("utf-8")).hexdigest(),
            encrypted_secret=self.secret_box.encrypt(secret),
            created_at=datetime.now(timezone.utc),
        )
        self.store.register_remote(profile, snapshot, record)
        return IssuedNodeCredential(
            node_id=profile.node_id,
            credential_id=record.credential_id,
            owner_scope=record.owner_scope,
            secret=secret,
        )

    def credential(self, node_id: str) -> ResourceCredentialRecord:
        """Read node credential metadata without exposing the plaintext secret."""
        self.store.get_profile(node_id)
        return self.store.get_credential(node_id)

    def credential_hmac_key(self, node_id: str, credential_id: str) -> bytes:
        """Decrypt a valid node credential only for request verification."""
        record = self.credential(node_id)
        if record.credential_id != credential_id:
            raise ValueError("node credential is invalid")
        secret = self.secret_box.decrypt(record.encrypted_secret)
        return hashlib.sha256(secret.encode("utf-8")).digest()

    def current_signing_credential(self, node_id: str) -> tuple[str, str]:
        """Return the current node credential for outbound remote execution."""
        record = self.credential(node_id)
        return record.credential_id, self.secret_box.decrypt(record.encrypted_secret)

    def verify_credential(
        self, node_id: str, credential_id: str, secret: str
    ) -> ResourceCredentialRecord:
        profile = self.store.get_profile(node_id)
        record = self.store.get_credential(node_id)
        expected_digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        if (
            record.credential_id != credential_id
            or record.owner_scope != profile.owner_scope
            or not hmac.compare_digest(record.secret_digest, expected_digest)
        ):
            raise ValueError("node credential is invalid")
        return record

    def consume_nonce(
        self,
        node_id: str,
        nonce: str,
        expires_at: datetime,
        *,
        now: datetime | None = None,
    ) -> bool:
        self.store.get_profile(node_id)
        current = now or datetime.now(timezone.utc)
        return self.store.consume_nonce(node_id, nonce, expires_at, now=current)

    def observe_remote(
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
        """Accept a signed remote node observation and persist snapshot plus health."""
        profile = self.store.get_profile(node_id)
        if profile.deployment_tier is DeploymentTier.LOCAL:
            raise ValueError("remote node observation requires a non-local node")
        current = self.store.get_snapshot(node_id)
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
        self.store.update_snapshot(snapshot, expected_version=current.version)
        return self.health_monitor.report(
            node_id,
            observed_at=timestamp,
            queued_tasks=queued_tasks,
            utilization=load,
            success=success,
        )

    def heartbeat(
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
        """节点上报一次心跳：刷新快照动态字段与健康投影。"""
        timestamp = observed_at if observed_at is not None else datetime.now(timezone.utc)
        current = self.store.get_snapshot(node_id)
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
        self.store.update_snapshot(snapshot, expected_version=current.version)
        return self.health_monitor.report(
            node_id,
            observed_at=timestamp,
            queued_tasks=queued_tasks,
            utilization=load,
            success=success,
        )

    def profile(self, node_id: str) -> NodeProfile:
        return self.store.get_profile(node_id)

    def snapshot(self, node_id: str) -> VersionedNodeSnapshot:
        return self.store.get_snapshot(node_id)

    def profiles(self) -> list[NodeProfile]:
        return self.store.list_profiles()

    def health(self, node_id: str, *, now: datetime | None = None) -> NodeHealth:
        live = self.health_monitor.health(node_id, now=now)
        if live.last_heartbeat is not None:
            return live
        snapshot = self.store.get_snapshot(node_id).snapshot
        if snapshot.last_heartbeat is None:
            return live
        current = now if now is not None else datetime.now(timezone.utc)
        age = current.astimezone(timezone.utc) - snapshot.last_heartbeat.astimezone(timezone.utc)
        if age > self.health_monitor.offline_threshold:
            status = NodeHealthStatus.OFFLINE
        elif age > self.health_monitor.stale_threshold:
            status = NodeHealthStatus.STALE
        else:
            status = snapshot.health_status
        return NodeHealth(
            node_id=node_id,
            status=status,
            last_heartbeat=snapshot.last_heartbeat,
            consecutive_failures=snapshot.consecutive_failures,
        )

    def candidates(
        self,
        *,
        min_gpu_memory_mb: int = 0,
        min_privacy_level: str | None = None,
        node_types: list[str] | None = None,
        now: datetime | None = None,
    ) -> list[NodeProfile]:
        """按硬约束过滤出健康可用的节点。"""
        selected: list[NodeProfile] = []
        for profile in self.store.list_profiles():
            if not profile.enabled:
                continue
            health = self.health(profile.node_id, now=now)
            if health.status in (NodeHealthStatus.STALE, NodeHealthStatus.OFFLINE):
                continue
            if profile.gpu_memory_mb < min_gpu_memory_mb:
                continue
            if (
                min_privacy_level is not None
                and _privacy_rank(profile.privacy_level) < _privacy_rank(min_privacy_level)
            ):
                continue
            if node_types and profile.node_type.value not in node_types:
                continue
            selected.append(profile)
        return selected
