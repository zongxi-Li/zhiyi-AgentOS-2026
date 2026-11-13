"""Explicit, frozen request budgets; estimates are never provider token usage."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModelRequestBudget(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    version: Literal["request-budget.v1"] = "request-budget.v1"
    total_tokens: int = Field(alias="totalTokens", ge=1, strict=True)
    output_reserve_tokens: int = Field(alias="outputReserveTokens", ge=1, strict=True)

    @model_validator(mode="after")
    def validate_reserve(self) -> "ModelRequestBudget":
        if self.output_reserve_tokens >= self.total_tokens:
            raise ValueError("output reserve must be smaller than total request budget")
        return self


class SupplementalReadBudget(BaseModel):
    """Frozen bounds for model-initiated reads, separate from initial prefetch."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)
    version: Literal["supplemental-read.v1"] = "supplemental-read.v1"
    max_read_tokens: int = Field(default=4096, alias="maxReadTokens", ge=1, strict=True)
    page_tokens: int = Field(default=1024, alias="pageTokens", ge=1, strict=True)
    total_tokens: int = Field(default=16384, alias="totalTokens", ge=1, strict=True)

    @model_validator(mode="after")
    def validate_limits(self) -> "SupplementalReadBudget":
        if self.page_tokens > self.max_read_tokens or self.max_read_tokens > self.total_tokens:
            raise ValueError("page <= read <= total budget is required")
        return self


__all__ = ["ModelRequestBudget", "SupplementalReadBudget"]
