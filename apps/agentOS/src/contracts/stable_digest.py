"""Canonical SHA-256 helpers with explicit, stable serialization semantics."""

import hashlib
import json
from typing import Any


def canonical_digest(value: Any) -> str:
    """Hash sorted compact JSON without dropping model defaults or nulls."""
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def model_digest(model: Any) -> str:
    """Hash the full JSON-mode, aliased Pydantic representation of a model."""
    return canonical_digest(model.model_dump(mode="json", by_alias=True))


__all__ = ["canonical_digest", "model_digest"]
