"""CAS store for immutable evolution policy versions."""

from __future__ import annotations

from threading import RLock

from contracts.evolution import EvolutionPolicyVersion


class EvolutionVersionConflict(ValueError):
    pass


class InMemoryEvolutionStore:
    def __init__(self) -> None:
        self._versions = {0: EvolutionPolicyVersion(version=0, policy={})}
        self._active = 0
        self._lock = RLock()

    def active(self) -> EvolutionPolicyVersion:
        return self._versions[self._active].model_copy(deep=True)

    def get(self, version: int) -> EvolutionPolicyVersion:
        try:
            return self._versions[version].model_copy(deep=True)
        except KeyError as exc:
            raise KeyError(f"unknown evolution policy version: {version}") from exc

    def list_versions(self) -> list[EvolutionPolicyVersion]:
        return [self._versions[key].model_copy(deep=True) for key in sorted(self._versions)]

    def create(self, value: EvolutionPolicyVersion, *, expected_active: int) -> EvolutionPolicyVersion:
        with self._lock:
            if expected_active != self._active or value.base_version != expected_active:
                raise EvolutionVersionConflict(
                    f"expected active evolution version {expected_active}, current {self._active}"
                )
            if value.version in self._versions or value.version != self._active + 1:
                raise EvolutionVersionConflict(f"invalid next evolution version: {value.version}")
            previous = self._versions[self._active]
            self._versions[self._active] = previous.model_copy(update={"status": "superseded"})
            self._versions[value.version] = value.model_copy(deep=True)
            self._active = value.version
            return value.model_copy(deep=True)


__all__ = ["EvolutionVersionConflict", "InMemoryEvolutionStore"]
