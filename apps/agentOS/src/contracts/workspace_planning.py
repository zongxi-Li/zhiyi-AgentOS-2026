"""Versioned workspace planning policy read from the accepted semantic plan."""
from __future__ import annotations

from contracts.execution_evidence import workspace_observation_requirements, workspace_requirement_contains_path


def workspace_planning_phase(plan) -> str | None:
    metadata = plan.metadata if hasattr(plan, "metadata") else (plan or {}).get("metadata", {})
    discovery = metadata.get("workspaceDiscovery")
    if not isinstance(discovery, dict) or discovery.get("version") != 1:
        return None
    phase = discovery.get("phase")
    return phase if phase in {"discovery", "formal"} else None


def _validated_scope(policy):
    if not isinstance(policy, dict) or type(policy.get("version")) is not int or policy["version"] != 1:
        raise ValueError("workspace scope revision requires workspaceScope version 1")
    requirements = workspace_observation_requirements(policy.get("requirements"))
    if not requirements:
        raise ValueError("workspace scope revision requires nonempty evidence requirements")
    if not isinstance(policy.get("rationale"), str) or not policy["rationale"].strip():
        raise ValueError("workspace scope revision requires a rationale")
    sources = policy.get("sourceRefs")
    if (not isinstance(sources, (list, tuple)) or not sources
            or any(not isinstance(ref, str) or not ref.strip() or any(c in ref for c in "\x00\r\n")
                   for ref in sources)):
        raise ValueError("workspace scope revision requires traceable sourceRefs")
    return requirements


def _covers_requirement(candidate, required):
    if required.kind == "file":
        if candidate.kind == "file":
            return candidate.path == required.path
        if candidate.operation != "read" or not workspace_requirement_contains_path(candidate, required.path):
            return False
        relative = required.path if candidate.path == "." else required.path[len(candidate.path) + 1:]
        return required.path != candidate.path and (candidate.recursive or "/" not in relative)
    if (candidate.kind != "directory" or not workspace_requirement_contains_path(candidate, required.path)
            or required.operation == "read" and candidate.operation != "read"
            or required.recursive and not candidate.recursive
            or candidate.path != required.path and not candidate.recursive):
        return False
    for excluded in candidate.exclude_paths:
        if not workspace_requirement_contains_path(required, excluded):
            continue
        relative = excluded if required.path == "." else excluded[len(required.path) + 1:]
        if required.recursive or "/" not in relative:
            return False
    return True


def _explicit_requirements(current, old_scope):
    requirements = workspace_observation_requirements(
        old_scope.get("requirements") if isinstance(old_scope, dict) else None)
    # The discovery plan preserves the caller's original scope on its ordinary
    # inspection node. No filesystem lookup or reconstruction is needed here.
    baseline = list(requirements)
    nodes = current.nodes if hasattr(current, "nodes") else current.get("nodes", ())
    for node in nodes:
        constraints = node.constraints if hasattr(node, "constraints") else node.get("constraints", ())
        for constraint in constraints:
            discovery = constraint.get("workspaceDiscovery")
            if isinstance(discovery, dict):
                baseline.extend(workspace_observation_requirements(discovery.get("requestedObservations")))
    return tuple(dict.fromkeys(baseline))


def explicit_workspace_requirements(plan):
    """Return the accepted explicit baseline for evidence-informed replanning."""
    metadata = plan.metadata if hasattr(plan, "metadata") else plan.get("metadata", {})
    discovery = metadata.get("workspaceDiscovery")
    if not isinstance(discovery, dict) or discovery.get("scopeOrigin") != "explicit":
        return ()
    return _explicit_requirements(plan, metadata.get("workspaceScope"))


def validate_workspace_plan_revision(current, metadata) -> None:
    """Check a merged metadata revision without granting execution authority.

    Historical plans retain their existing revision contract. New discovery
    plans retain their origin and move forward to a grounded formal scope.
    Reference resolution and receipt verification remain with runtime authority.
    """
    phase = workspace_planning_phase(current)
    if phase is None:
        if workspace_planning_phase({"metadata": metadata}) is not None:
            raise ValueError("workspace discovery protocol must be declared by the initial plan")
        return
    previous = current.metadata if hasattr(current, "metadata") else current.get("metadata", {})
    original = previous["workspaceDiscovery"]
    revised = metadata.get("workspaceDiscovery")
    if (not isinstance(revised, dict) or type(revised.get("version")) is not int
            or revised["version"] != 1 or revised.get("phase") not in {"discovery", "formal"}):
        raise ValueError("workspace planning revision must preserve its versioned discovery protocol")
    origin = original.get("scopeOrigin")
    if origin not in {"explicit", "inferred"} or revised.get("scopeOrigin") != origin:
        raise ValueError("workspace planning revision cannot change scopeOrigin")
    if phase == "formal" and revised["phase"] != "formal":
        raise ValueError("formal workspace planning cannot return to discovery")
    old_scope, scope = previous.get("workspaceScope"), metadata.get("workspaceScope")
    if revised["phase"] != "formal" or phase == "formal" and scope == old_scope:
        return
    requirements = _validated_scope(scope)
    if origin == "explicit" and any(not any(_covers_requirement(candidate, required) for candidate in requirements)
            for required in _explicit_requirements(current, old_scope)):
        raise ValueError("workspace scope revision cannot reduce explicit evidence requirements")


def effective_workspace_requirements(run):
    """Preserve caller requirements; inferred scope follows accepted revisions.

    A historical Run with no discovery protocol retains its original obligation.
    Tool authorization is independently revalidated at every actual invocation.
    """
    state = run.execution_state
    frozen = workspace_observation_requirements(state.get("workspaceObservations"))
    plan = state.get("taskPlan") or {}
    phase = workspace_planning_phase(plan)
    if phase != "formal":
        return frozen
    metadata = plan.get("metadata", {})
    discovery = metadata["workspaceDiscovery"]
    if discovery.get("scopeOrigin") != "inferred" or "workspaceObservations" in run.input:
        return frozen
    policy = metadata.get("workspaceScope")
    if not isinstance(policy, dict) or policy.get("version") != 1:
        return frozen
    requirements = workspace_observation_requirements(policy.get("requirements"))
    if not requirements:
        raise ValueError("workspace planning cannot discard every evidence requirement")
    if not isinstance(policy.get("rationale"), str) or not policy["rationale"].strip():
        raise ValueError("workspace scope revision requires a rationale")
    return requirements
