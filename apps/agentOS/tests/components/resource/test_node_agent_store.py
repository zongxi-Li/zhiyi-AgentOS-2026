from __future__ import annotations

from datetime import datetime, timedelta, timezone

from contracts.resource import (
    AgentProfile,
    AgentSnapshot,
    DeploymentTier,
    NodeProfile,
    NodeSnapshot,
    NodeType,
    ResourceEndpoint,
)
from components.resource.agent_store import SQLiteAgentStore
from components.resource.node_service import NodeService
from components.resource.node_store import SQLiteNodeStore
from components.resource.store import ResourceCredentialRecord


def test_sqlite_node_store_persists_profile_snapshot_credential_and_nonce(tmp_path) -> None:
    db_path = tmp_path / "nodes.sqlite3"
    store = SQLiteNodeStore(db_path)
    profile = NodeProfile(
        nodeId="edge-01",
        nodeType=NodeType.WORKER,
        deploymentTier=DeploymentTier.EDGE,
        ownerScope="tenant-a",
        gpuMemoryMb=24576,
        modelIds=["vision-large"],
        executionEndpoint=ResourceEndpoint(protocol="http", address="http://edge/execute"),
    )
    snapshot = NodeSnapshot(nodeId="edge-01", availableMemoryMb=16384, observationSequence=1)
    credential = ResourceCredentialRecord(
        resource_id="edge-01",
        credential_id="nc_test",
        owner_scope="tenant-a",
        secret_digest="digest",
        encrypted_secret="encrypted",
        created_at=datetime(2026, 9, 11, tzinfo=timezone.utc),
    )

    store.register_remote(profile, snapshot, credential)
    assert store.consume_nonce(
        "edge-01",
        "nonce-1",
        datetime(2026, 9, 11, 0, 5, tzinfo=timezone.utc),
        now=datetime(2026, 9, 11, tzinfo=timezone.utc),
    )
    store.close()

    reopened = SQLiteNodeStore(db_path)

    assert reopened.get_profile("edge-01") == profile
    assert reopened.get_snapshot("edge-01").snapshot == snapshot
    assert reopened.get_credential("edge-01") == credential
    assert not reopened.consume_nonce(
        "edge-01",
        "nonce-1",
        datetime(2026, 9, 11, 0, 6, tzinfo=timezone.utc),
        now=datetime(2026, 9, 11, 0, 1, tzinfo=timezone.utc),
    )
    assert reopened.consume_nonce(
        "edge-01",
        "nonce-2",
        datetime(2026, 9, 11, 0, 6, tzinfo=timezone.utc),
        now=datetime(2026, 9, 11, 0, 1, tzinfo=timezone.utc),
    )


def test_sqlite_agent_store_persists_profile_and_snapshot(tmp_path) -> None:
    db_path = tmp_path / "agents.sqlite3"
    store = SQLiteAgentStore(db_path)
    profile = AgentProfile(
        agentId="contract-agent",
        capabilities=["legal_review", "agent:contract"],
        requiredModelIds=["deepseek-law"],
        allowedNodeIds=["edge-01"],
        minPrivacyLevel="confidential",
    )
    snapshot = AgentSnapshot(agentId="contract-agent", observationSequence=3, successRate=0.8)

    store.register(profile, snapshot)
    store.close()

    reopened = SQLiteAgentStore(db_path)

    assert reopened.get_profile("contract-agent") == profile
    versioned = reopened.get_snapshot("contract-agent")
    assert versioned.snapshot == snapshot
    assert versioned.version == 1


def test_sqlite_node_store_expires_old_nonces_on_consume(tmp_path) -> None:
    store = SQLiteNodeStore(tmp_path / "nodes.sqlite3")
    profile = NodeProfile(nodeId="edge-01", deploymentTier=DeploymentTier.EDGE)
    store.register(profile, NodeSnapshot(nodeId="edge-01"))
    now = datetime(2026, 9, 11, tzinfo=timezone.utc)

    assert store.consume_nonce("edge-01", "short", now + timedelta(seconds=1), now=now)
    assert store.consume_nonce(
        "edge-01",
        "short",
        now + timedelta(minutes=1),
        now=now + timedelta(seconds=2),
    )


def test_node_service_health_recovers_from_persisted_snapshot_after_restart(tmp_path) -> None:
    db_path = tmp_path / "nodes.sqlite3"
    first = NodeService(store=SQLiteNodeStore(db_path))
    first.register(
        NodeProfile(nodeId="edge-01", deploymentTier=DeploymentTier.EDGE),
        NodeSnapshot(nodeId="edge-01"),
    )
    first.observe_remote(
        "edge-01",
        observation_sequence=1,
        cpu_utilization=0.2,
        gpu_utilization=0.1,
        observed_at=datetime(2026, 9, 11, tzinfo=timezone.utc),
    )
    first.store.close()

    reopened = NodeService(store=SQLiteNodeStore(db_path))

    assert reopened.health(
        "edge-01",
        now=datetime(2026, 9, 11, 0, 0, 1, tzinfo=timezone.utc),
    ).status.value == "online"
    assert reopened.health(
        "edge-01",
        now=datetime(2026, 9, 11, 0, 0, 20, tzinfo=timezone.utc),
    ).status.value == "stale"
    assert reopened.health(
        "edge-01",
        now=datetime(2026, 9, 11, 0, 0, 40, tzinfo=timezone.utc),
    ).status.value == "offline"


def test_node_service_persists_consecutive_failures_in_snapshot(tmp_path) -> None:
    db_path = tmp_path / "nodes.sqlite3"
    service = NodeService(store=SQLiteNodeStore(db_path))
    service.register(
        NodeProfile(nodeId="edge-01", deploymentTier=DeploymentTier.EDGE),
        NodeSnapshot(nodeId="edge-01"),
    )

    service.observe_remote(
        "edge-01",
        observation_sequence=1,
        observed_at=datetime(2026, 9, 11, tzinfo=timezone.utc),
        success=False,
    )
    service.store.close()

    reopened = NodeService(store=SQLiteNodeStore(db_path))

    assert reopened.snapshot("edge-01").snapshot.consecutive_failures == 1
    assert reopened.health(
        "edge-01",
        now=datetime(2026, 9, 11, 0, 0, 1, tzinfo=timezone.utc),
    ).consecutive_failures == 1
