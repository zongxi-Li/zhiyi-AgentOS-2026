"""Validate AgentOS model partitions without claiming an executable backend."""

from __future__ import annotations

from typing import Any

from contracts.model_partition import ModelPartitionPlan


class ModelPartitionUnavailableError(RuntimeError):
    code = "MODEL_PARTITION_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__(self.code)


class ModelPartitionService:
    """Preserve the plan validation and explicit unavailable execution contract."""

    def validate(self, plan: ModelPartitionPlan) -> ModelPartitionPlan:
        return ModelPartitionPlan.model_validate(plan.model_dump(by_alias=True))

    def execute(self, plan: ModelPartitionPlan, input_payload: dict[str, Any]) -> None:
        self.validate(plan)
        if not isinstance(input_payload, dict):
            raise TypeError("model partition input must be an object")
        raise ModelPartitionUnavailableError()


__all__ = ["ModelPartitionService", "ModelPartitionUnavailableError"]
