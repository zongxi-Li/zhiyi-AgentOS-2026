"""Agent definitions and exact registration identities, independent of Step/ACG."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator


class AgentDefinition(BaseModel):
    """Immutable declaration; capacity, health and admission are instance facts."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    agent_id: StrictStr = Field(alias="agentId", min_length=1)
    agent_name: StrictStr = Field(alias="agentName", min_length=1)
    domain: StrictStr = Field(min_length=1)
    definition_version: StrictStr | None = Field(default=None, alias="definitionVersion")
    execution_mode: Literal["unspecified", "stateless", "stateful"] = Field(default="unspecified", alias="executionMode")
    capabilities: tuple[StrictStr, ...] = ()
    allowed_skills: tuple[StrictStr, ...] = Field(default=(), alias="allowedSkills")
    allowed_tools: tuple[StrictStr, ...] = Field(default=(), alias="allowedTools")
    model_provider: StrictStr | None = Field(default=None, alias="modelProvider")
    model_name: StrictStr | None = Field(default=None, alias="modelName")
    model_version: StrictStr | None = Field(default=None, alias="modelVersion")
    risk_level: StrictStr = Field(default="normal", alias="riskLevel")
    binding_priority: int = Field(default=0, alias="bindingPriority")
    description: StrictStr = ""
    source: Literal["native", "plugin"] = "native"
    plugin_id: StrictStr | None = Field(default=None, alias="pluginId")
    plugin_version: StrictStr | None = Field(default=None, alias="pluginVersion")
    contribution_id: StrictStr | None = Field(default=None, alias="contributionId")

    @field_validator("agent_id", "agent_name", "domain", "definition_version")
    @classmethod
    def nonblank(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Agent definition identity must not be blank")
        return value.strip() if value is not None else None

    @property
    def digest(self) -> str:
        data = json.dumps(self.model_dump(mode="json", by_alias=True), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(data.encode("utf-8")).hexdigest()


class AgentRegistrationRef(BaseModel):
    """Process registry epoch + instance identity + generation; never a lease."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    registry_id: StrictStr = Field(alias="registryId", min_length=1)
    instance_id: StrictStr = Field(alias="instanceId", min_length=1)
    agent_id: StrictStr = Field(alias="agentId", min_length=1)
    generation: int = Field(ge=1, strict=True)
    definition_digest: StrictStr = Field(alias="definitionDigest", min_length=1)
    definition_version: StrictStr | None = Field(default=None, alias="definitionVersion")

    @field_validator("registry_id", "instance_id", "agent_id", "definition_digest", "definition_version")
    @classmethod
    def nonblank(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Agent registration identity must not be blank")
        return value.strip() if value is not None else None

    @property
    def resource_id(self) -> str:
        # Every generation gets an independent resource/health namespace. Old
        # observations cannot mutate a replacement, even across registry restarts.
        data = self.model_dump_json(by_alias=True)
        return "agent-executor:" + hashlib.sha256(data.encode("utf-8")).hexdigest()


__all__ = ["AgentDefinition", "AgentRegistrationRef"]
