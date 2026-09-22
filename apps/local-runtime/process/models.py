"""Validated, structured input for native process execution."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator

from contracts.local_runtime import ExecutionSecurityProfile


class ProcessExecutionMode(str, Enum):
    DIRECT = "direct"
    SHELL = "shell"


class ProcessExecutionRequest(BaseModel):
    """A process request whose cwd is always interpreted inside an authority root."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    mode: ProcessExecutionMode = ProcessExecutionMode.DIRECT
    security_profile: ExecutionSecurityProfile = Field(
        default=ExecutionSecurityProfile.HOST_APPROVED,
        alias="securityProfile",
    )
    program: StrictStr | None = Field(default=None, min_length=1)
    args: list[StrictStr] = Field(default_factory=list)
    command: StrictStr | None = Field(default=None, min_length=1)
    cwd: StrictStr = Field(default=".", min_length=1)
    env: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    timeout_seconds: float | None = Field(default=None, alias="timeout", gt=0)

    @model_validator(mode="after")
    def validate_mode_shape(self) -> "ProcessExecutionRequest":
        if self.mode is ProcessExecutionMode.DIRECT:
            if not self.program:
                raise ValueError("direct process execution requires program")
            if self.command is not None:
                raise ValueError("direct process execution does not accept command")
        else:
            if not self.command:
                raise ValueError("shell process execution requires command")
            if self.program is not None or self.args:
                raise ValueError("shell process execution does not accept program or args")
        return self


__all__ = ["ProcessExecutionMode", "ProcessExecutionRequest"]
