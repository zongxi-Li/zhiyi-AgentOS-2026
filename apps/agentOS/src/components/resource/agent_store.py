"""Agent 注册表的存储实现（协议 + 进程内存）。"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Protocol

from contracts.resource import AgentProfile, AgentSnapshot

from .models import VersionedAgentSnapshot
from .store import StaleResourceObservation, VersionConflict


class AgentStore(Protocol):
    """Agent 注册表依赖的最小存储边界，便于替换存储介质。"""

    def register(self, profile: AgentProfile, snapshot: AgentSnapshot) -> VersionedAgentSnapshot:
        """登记匹配的 Agent 画像与首份快照；重复登记抛出 ``ValueError``。"""
        ...

    def get_profile(self, agent_id: str) -> AgentProfile:
        """读取 Agent 画像副本；未知标识抛出 ``KeyError``。"""
        ...

    def get_snapshot(self, agent_id: str) -> VersionedAgentSnapshot:
        """读取当前版本快照副本；未知标识抛出 ``KeyError``。"""
        ...

    def list_profiles(self) -> list[AgentProfile]:
        """返回稳定顺序的 Agent 画像副本列表。"""
        ...

    def update_snapshot(
        self, snapshot: AgentSnapshot, *, expected_version: int | None = None
    ) -> VersionedAgentSnapshot:
        """按可选期望版本原子更新快照；过期版本抛出 ``VersionConflict``。"""
        ...


class InMemoryAgentStore:
    """面向单进程运行的 Agent 注册存储。"""

    def __init__(self) -> None:
        self._profiles: dict[str, AgentProfile] = {}
        self._snapshots: dict[str, VersionedAgentSnapshot] = {}
        self._lock = RLock()

    def register(self, profile: AgentProfile, snapshot: AgentSnapshot) -> VersionedAgentSnapshot:
        if profile.agent_id != snapshot.agent_id:
            raise ValueError("profile and snapshot agentId must match")
        with self._lock:
            if profile.agent_id in self._profiles:
                current_profile = self._profiles[profile.agent_id]
                current_snapshot = self._snapshots[profile.agent_id]
                if current_profile == profile and current_snapshot.snapshot == snapshot:
                    return self._copy(current_snapshot)
                raise ValueError(f"agent already registered: {profile.agent_id}")
            self._profiles[profile.agent_id] = profile.model_copy(deep=True)
            versioned = VersionedAgentSnapshot(snapshot=snapshot.model_copy(deep=True), version=1)
            self._snapshots[profile.agent_id] = versioned
            return self._copy(versioned)

    def get_profile(self, agent_id: str) -> AgentProfile:
        try:
            return self._profiles[agent_id].model_copy(deep=True)
        except KeyError as error:
            raise KeyError(f"unknown agent: {agent_id}") from error

    def get_snapshot(self, agent_id: str) -> VersionedAgentSnapshot:
        try:
            return self._copy(self._snapshots[agent_id])
        except KeyError as error:
            raise KeyError(f"unknown agent: {agent_id}") from error

    def list_profiles(self) -> list[AgentProfile]:
        return [self._profiles[key].model_copy(deep=True) for key in sorted(self._profiles)]

    def update_snapshot(
        self, snapshot: AgentSnapshot, *, expected_version: int | None = None
    ) -> VersionedAgentSnapshot:
        with self._lock:
            try:
                current = self._snapshots[snapshot.agent_id]
            except KeyError as error:
                raise KeyError(f"unknown agent: {snapshot.agent_id}") from error
            if expected_version is not None and expected_version != current.version:
                raise VersionConflict(
                    f"snapshot version conflict for {snapshot.agent_id}: "
                    f"expected {expected_version}, current {current.version}"
                )
            if snapshot.observation_sequence < current.snapshot.observation_sequence:
                raise StaleResourceObservation(
                    f"stale observation for {snapshot.agent_id}: "
                    f"received {snapshot.observation_sequence}, "
                    f"current {current.snapshot.observation_sequence}"
                )
            versioned = VersionedAgentSnapshot(
                snapshot=snapshot.model_copy(deep=True), version=current.version + 1
            )
            self._snapshots[snapshot.agent_id] = versioned
            return self._copy(versioned)

    @staticmethod
    def _copy(value: VersionedAgentSnapshot) -> VersionedAgentSnapshot:
        return VersionedAgentSnapshot(snapshot=value.snapshot.model_copy(deep=True), version=value.version)


class SQLiteAgentStore:
    """SQLite-backed Agent registry using JSON contracts plus CAS versions."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS agents (
                agent_id TEXT PRIMARY KEY,
                profile_json TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                version INTEGER NOT NULL CHECK(version >= 1)
            )"""
        )
        self._connection.commit()
        self._lock = RLock()

    @staticmethod
    def _json(model: AgentProfile | AgentSnapshot) -> str:
        return json.dumps(
            model.model_dump(by_alias=True, mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _snapshot(row: tuple[object, object]) -> VersionedAgentSnapshot:
        return VersionedAgentSnapshot(
            snapshot=AgentSnapshot.model_validate(json.loads(str(row[0]))),
            version=int(row[1]),
        )

    def register(self, profile: AgentProfile, snapshot: AgentSnapshot) -> VersionedAgentSnapshot:
        if profile.agent_id != snapshot.agent_id:
            raise ValueError("profile and snapshot agentId must match")
        with self._lock:
            row = self._connection.execute(
                "SELECT profile_json, snapshot_json, version FROM agents WHERE agent_id = ?",
                (profile.agent_id,),
            ).fetchone()
            if row is not None:
                current_profile = AgentProfile.model_validate(json.loads(str(row[0])))
                current_snapshot = AgentSnapshot.model_validate(json.loads(str(row[1])))
                if current_profile == profile and current_snapshot == snapshot:
                    return self._snapshot((row[1], row[2]))
                raise ValueError(f"agent already registered: {profile.agent_id}")
            self._connection.execute(
                "INSERT INTO agents(agent_id, profile_json, snapshot_json, version) VALUES (?, ?, ?, 1)",
                (profile.agent_id, self._json(profile), self._json(snapshot)),
            )
            self._connection.commit()
            return VersionedAgentSnapshot(snapshot=snapshot.model_copy(deep=True), version=1)

    def get_profile(self, agent_id: str) -> AgentProfile:
        row = self._connection.execute(
            "SELECT profile_json FROM agents WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown agent: {agent_id}")
        return AgentProfile.model_validate(json.loads(str(row[0])))

    def get_snapshot(self, agent_id: str) -> VersionedAgentSnapshot:
        row = self._connection.execute(
            "SELECT snapshot_json, version FROM agents WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown agent: {agent_id}")
        return self._snapshot(row)

    def list_profiles(self) -> list[AgentProfile]:
        rows = self._connection.execute(
            "SELECT profile_json FROM agents ORDER BY agent_id"
        ).fetchall()
        return [AgentProfile.model_validate(json.loads(str(row[0]))) for row in rows]

    def update_snapshot(
        self, snapshot: AgentSnapshot, *, expected_version: int | None = None
    ) -> VersionedAgentSnapshot:
        with self._lock:
            row = self._connection.execute(
                "SELECT snapshot_json, version FROM agents WHERE agent_id = ?",
                (snapshot.agent_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown agent: {snapshot.agent_id}")
            current_snapshot = AgentSnapshot.model_validate(json.loads(str(row[0])))
            current_version = int(row[1])
            if expected_version is not None and expected_version != current_version:
                raise VersionConflict(
                    f"snapshot version conflict for {snapshot.agent_id}: "
                    f"expected {expected_version}, current {current_version}"
                )
            if snapshot.observation_sequence < current_snapshot.observation_sequence:
                raise StaleResourceObservation(
                    f"stale observation for {snapshot.agent_id}: "
                    f"received {snapshot.observation_sequence}, "
                    f"current {current_snapshot.observation_sequence}"
                )
            next_version = current_version + 1
            cursor = self._connection.execute(
                "UPDATE agents SET snapshot_json = ?, version = ? WHERE agent_id = ? AND version = ?",
                (self._json(snapshot), next_version, snapshot.agent_id, current_version),
            )
            if cursor.rowcount != 1:
                self._connection.rollback()
                raise VersionConflict(f"snapshot version conflict for {snapshot.agent_id}")
            self._connection.commit()
            return VersionedAgentSnapshot(snapshot=snapshot.model_copy(deep=True), version=next_version)

    def close(self) -> None:
        self._connection.close()
