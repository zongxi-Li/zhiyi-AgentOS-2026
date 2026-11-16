"""Deterministic selection of the current feasible execution frontier."""

from collections.abc import Iterable, Mapping


def dependency_status(
    predecessors: set[str],
    join_groups: Iterable[set[str]],
    completed: set[str],
    skipped: set[str],
) -> str:
    """Treat an unselected conditional branch as waived only at its declared join."""
    groups = tuple(join_groups)
    waived = set().union(*groups) if groups else set()
    if (predecessors & skipped) - waived or any(group <= skipped for group in groups):
        return "skip"
    if not predecessors <= completed | skipped:
        return "wait"
    return "ready"


def select_ready_steps(
    node_ids: Iterable[str],
    *,
    step_ids: set[str],
    predecessors: Mapping[str, set[str]],
    completed: Iterable[str],
    active: Iterable[str] = (),
    skipped: Iterable[str] = (),
    join_groups: Mapping[str, Iterable[set[str]]] | None = None,
    limit: int | None = None,
) -> tuple[str, ...]:
    """Select eligible steps in graph order; a capacity limit never overrides dependencies.

    Resource eligibility and leases remain owned by the resource service. Callers
    pass already approved nodes; this function introduces no allocation authority.
    """
    if limit is not None and limit < 0:
        raise ValueError("execution frontier limit must be non-negative")
    if limit == 0:
        return ()
    completed_set, skipped_set = set(completed), set(skipped)
    inactive = completed_set | skipped_set | set(active)
    groups = join_groups or {}
    result = []
    for node_id in node_ids:
        if node_id not in step_ids or node_id in inactive:
            continue
        if dependency_status(predecessors.get(node_id, set()), groups.get(node_id, ()), completed_set, skipped_set) == "ready":
            result.append(node_id)
            if limit is not None and len(result) >= limit:
                break
    return tuple(result)
