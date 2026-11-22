"""Model-facing plan context over immutable accepted workspace semantics."""
from __future__ import annotations

from collections import deque
from typing import Any

from contracts import stable_checksum
from contracts.planning import TaskPlan
from contracts.runtime_planning import RuntimePlanningObservation
from contracts.workspace_planning import workspace_planning_phase


def _settled_frontier(keys, settled, successors):
    """Find every settled branch tip, including paths through non-task parents."""
    indegree = dict.fromkeys(keys, 0)
    for targets in successors.values():
        for target in targets:
            indegree[target] += 1
    ready = deque(key for key in keys if indegree[key] == 0)
    ordered = []
    while ready:
        key = ready.popleft()
        ordered.append(key)
        for target in successors.get(key, ()):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    reaches_settled = {}
    for key in reversed(ordered):
        reaches_settled[key] = any(target in settled or reaches_settled[target]
            for target in successors.get(key, ()))
    return {key for key in settled if not reaches_settled.get(key, False)}


def planning_task_plan_context(
    task_plan: TaskPlan, observation: RuntimePlanningObservation,
) -> dict[str, Any]:
    """Keep current semantics complete without replaying every settled page.

    All task identities and relations remain visible. Current work, every
    settled causal frontier and its direct evidence dependencies retain full
    semantics, as does the discovery prefix. Earlier settled work retains its
    identity and committed references rather than repeated objectives/targets.
    This read view never changes the accepted plan or its revision authority.
    """
    accepted = task_plan.model_dump(by_alias=True, mode="json")
    if workspace_planning_phase(task_plan) != "formal":
        return accepted

    known = {node.key for node in task_plan.nodes}
    steps = {step.task_key: step for step in observation.steps if step.task_key in known}
    remaining = set(observation.remaining_step_ids)
    settled = {key for key, step in steps.items()
        if step.status in {"completed", "skipped"} and step.step_id not in remaining}
    successors, predecessors = {}, {}
    for relation in task_plan.relations:
        if relation.relation_type.value == "depends_on":
            successors.setdefault(relation.source_key, set()).add(relation.target_key)
            predecessors.setdefault(relation.target_key, set()).add(relation.source_key)
    frontier = _settled_frontier(known, settled, successors)
    discovery = {node.key for node in task_plan.nodes
        if node.logical_role == "workspace_discovery"
        or node.metadata.get("source") == "workspace_discovery"
        or node.key.startswith("workspace_discovery:")}
    # Only the frontier's direct evidence dependencies need their old bodies.
    # Following all ancestors (or every redundant edge into a pending final
    # task) would expand the entire settled history again after each revision.
    full = (known - settled) | frontier | discovery
    full.update(parent for key in frontier for parent in predecessors.get(key, ()))
    direct_context = frozenset(full)
    full.update(node.parent_key for node in task_plan.nodes if node.key in direct_context and node.parent_key)
    nodes = []
    for original in accepted["nodes"]:
        key = original["key"]
        if key in full:
            nodes.append(original)
            continue
        step = steps[key]
        summary = {field: original[field] for field in (
            "key", "parentKey", "title", "capabilityRequirements", "logicalRole",
            "sourceRefs", "producedArtifacts")}
        summary.update(contextDetail="settled_summary", status=step.status,
            outputRef=step.output_ref, commitId=step.commit_id,
            auditRef=step.audit_ref, auditOutcome=step.audit_outcome,
            verificationReport=step.verification_report, artifactRefs=list(step.artifact_refs))
        nodes.append(summary)
    return {
        **accepted,
        "nodes": nodes,
        "contextProjection": {
            "version": 1,
            "acceptedPlanFingerprint": stable_checksum(accepted),
            "fullNodeCount": len(full),
            "summarizedNodeCount": len(known - full),
            "meaning": "Model read view of the accepted plan. Every task identity and relation is present. "
                "Settled summaries omit historical objectives, constraints and worksets; their accepted "
                "semantics and committed evidence remain unchanged. Use the current observation and source "
                "references for results. This projection is not a replacement TaskPlan or permission to "
                "rerun settled tasks, weaken requirements or alter their committed results.",
        },
    }


def planning_workspace_material_context(material, observation, *, readable=False):
    """Deliver the sealed material address when the same reader can expand it.

    The immutable source snapshot, its verification and its full contents remain
    unchanged. Legacy/injected planners without that read capability keep the
    complete supplied material rather than receiving an unusable reference.
    """
    if not readable:
        return material
    discovery = observation.workspace_discovery or {}
    entry = next((item for item in observation.context_catalog
                  if item.context_kind == "workspace_material" and item.status == "available"
                  and item.original_ref == discovery.get("contextRef")), None)
    if entry is None:
        return material
    return {
        "delivery": "reference",
        "contextRef": entry.context_ref,
        "contextKind": entry.context_kind,
        "checksum": entry.checksum,
        "fields": [field.name for field in entry.fields],
        "sourceRefs": list(discovery.get("sourceRefs") or ()),
        "verifiedObservationCount": discovery.get("verifiedObservationCount"),
        "meaning": "Sealed workspace findings and authenticated observations are readable in full via "
            "contextRef. Read the relevant fields or nested paths before deciding when their contents "
            "matter. Agent findings remain claims to verify; authenticated observations prove only their "
            "named operations. An omitted body is not missing work or permission to rescan files.",
    }


__all__ = ["planning_task_plan_context", "planning_workspace_material_context"]
