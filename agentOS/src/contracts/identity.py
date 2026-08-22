"""统一定义 AgentOS 新领域模型使用的稳定身份。"""

from __future__ import annotations

import re
from typing import Annotated, TypeAlias
from uuid import uuid4

from pydantic import AfterValidator


_HEX_LENGTH = 12
_PREFIXES = {
    "mission",
    "task",
    "blueprint",
    "run",
    "attempt",
    "binding",
    "step_execution",
}


def validate_identity(value: str, *, prefix: str) -> str:
    """校验一个带固定前缀的 12 位十六进制身份。"""
    if prefix not in _PREFIXES:
        raise ValueError(f"unsupported identity prefix: {prefix}")
    if not isinstance(value, str):
        raise TypeError("identity must be a string")
    pattern = rf"{re.escape(prefix)}_[0-9a-f]{{{_HEX_LENGTH}}}"
    if re.fullmatch(pattern, value) is None:
        raise ValueError(f"identity must match {prefix}_<12 lowercase hex>")
    return value


def generate_identity(prefix: str) -> str:
    """通过唯一入口生成 AgentOS 领域身份。"""
    if prefix not in _PREFIXES:
        raise ValueError(f"unsupported identity prefix: {prefix}")
    return f"{prefix}_{uuid4().hex[:_HEX_LENGTH]}"


def _validator(prefix: str):
    return AfterValidator(lambda value: validate_identity(value, prefix=prefix))


MissionId: TypeAlias = Annotated[str, _validator("mission")]
TaskId: TypeAlias = Annotated[str, _validator("task")]
BlueprintId: TypeAlias = Annotated[str, _validator("blueprint")]
RunId: TypeAlias = Annotated[str, _validator("run")]
AttemptId: TypeAlias = Annotated[str, _validator("attempt")]
BindingId: TypeAlias = Annotated[str, _validator("binding")]
StepExecutionId: TypeAlias = Annotated[str, _validator("step_execution")]


def new_mission_id() -> str:
    return generate_identity("mission")


def new_task_id() -> str:
    return generate_identity("task")


def new_blueprint_id() -> str:
    return generate_identity("blueprint")


def new_run_id() -> str:
    return generate_identity("run")


def new_attempt_id() -> str:
    return generate_identity("attempt")


def new_binding_id() -> str:
    return generate_identity("binding")


def new_step_execution_id() -> str:
    return generate_identity("step_execution")


__all__ = [
    "AttemptId",
    "BindingId",
    "BlueprintId",
    "RunId",
    "StepExecutionId",
    "TaskId",
    "MissionId",
    "generate_identity",
    "new_attempt_id",
    "new_binding_id",
    "new_blueprint_id",
    "new_run_id",
    "new_step_execution_id",
    "new_task_id",
    "new_mission_id",
    "validate_identity",
]
