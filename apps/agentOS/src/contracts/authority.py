"""Explicit identity types used at the planning/runtime binding boundary."""

from typing import NewType


# These aliases intentionally serialize as strings. They make the authority
# boundary explicit in type signatures without changing the V4 wire contract.
LogicalAgentId = NewType("LogicalAgentId", str)
RuntimeResourceId = NewType("RuntimeResourceId", str)


__all__ = ["LogicalAgentId", "RuntimeResourceId"]
