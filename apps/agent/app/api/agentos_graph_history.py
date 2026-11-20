"""Read-only graph history from immutable Identity snapshots and handoff facts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from contracts.recovery import GraphPatch
from contracts.acg.schema import RuntimeBlueprintSpec
from support.stores.planning_commit_store import content_fingerprint


@dataclass(frozen=True)
class RunGraphHistory:
    projection: dict[str, Any]
    snapshots: dict[str, dict[str, Any]]


def _version(graph):
    value = graph.get("version") or graph.get("graphVersion")
    return value if type(value) is int and value > 0 else None


def _patch_projection(patch):
    if patch is None:
        return None
    return {"patchId": patch.patch_id,
        "addedNodeIds": [n["nodeId"] for n in patch.added_nodes],
        "updatedNodeIds": [n["nodeId"] for n in patch.updated_nodes],
        "removedNodeIds": list(patch.removed_node_ids),
        "addedEdgeCount": len(patch.added_edges), "removedEdgeCount": len(patch.removed_edges)}


def _accepted_revision(runtime, run, activation, graph):
    """An accepted revision binds this Run and both exact graph contents."""
    if activation is None or activation.source_kind != "graph_revision":
        return None
    authority = getattr(runtime, "planning_commit_authority", None)
    commit = authority.get_commit(activation.source_commit_id) if authority is not None else None
    proposal = getattr(commit, "proposal_payload", None)
    origin = getattr(proposal, "source_provenance", None)
    candidate = getattr(proposal, "candidate_graph", None)
    proof = getattr(proposal, "safe_cut", None)
    patch = getattr(proposal, "graph_patch", None)
    if (getattr(commit, "status", None) != "ACCEPTED"
            or getattr(commit, "mission_id", None) != run.mission_id
            or getattr(commit, "proposal_type", None) != "graph_revision"
            or getattr(proposal, "mission_id", None) != run.mission_id
            or getattr(origin, "source_run_id", None) != run.run_id
            or getattr(origin, "graph_id", None) != activation.graph_id
            or candidate is None or proof is None or patch is None
            or candidate.graph_id != activation.graph_id
            or candidate.version != activation.candidate_graph_version
            or patch.base_graph_version != activation.source_graph_version
            or patch.graph_version != activation.candidate_graph_version
            or patch.graph_id != activation.graph_id
            or content_fingerprint(RuntimeBlueprintSpec.model_validate(graph)) != proof.candidate_graph_fingerprint):
        return None
    return proposal


def _source_snapshot(blueprint, run, activation, proposal):
    """Identity can lag activation; prove its pinned source before following it."""
    if (blueprint is None or proposal is None or blueprint.mission_id != run.mission_id
            or blueprint.graph_id != activation.graph_id
            or _version(blueprint.graph) != activation.source_graph_version
            or content_fingerprint(RuntimeBlueprintSpec.model_validate(blueprint.graph))
                != proposal.safe_cut.source_graph_fingerprint):
        return None
    return blueprint


def graph_history(runtime, run, repositories=None) -> RunGraphHistory:
    """Follow this Run's handoffs or accepted source proofs, never Mission siblings.

    Blueprint.version is a Mission-wide Identity sequence. Display and compare
    the embedded runtime graph version instead. A paused activation can precede
    its Identity projection, so its blueprintId and createdAt remain absent.
    """
    identity = repositories.runs.get(run.run_id) if repositories is not None else None
    identity_blueprint = repositories.blueprints.get(identity.blueprint_id) if identity is not None else None
    current_blueprint = identity_blueprint
    graph = dict(run.acg_blueprint or (current_blueprint.graph if current_blueprint else {}))
    graph_id = graph.get("graphId") or run.execution_state.get("graphId")
    current_version = _version(graph) or run.execution_state.get("graphVersion")
    if current_blueprint is not None and current_blueprint.mission_id != run.mission_id:
        raise ValueError("graph snapshot belongs to another Mission")
    if current_blueprint is not None and current_blueprint.graph != graph:
        current_blueprint = None  # Activation is real; Identity may still be behind its permit.
    projection = {"runId": run.run_id, "graphId": graph_id,
        "currentBlueprintId": current_blueprint.blueprint_id if current_blueprint else None,
        "currentGraphVersion": current_version, "items": [], "proposals": []}
    snapshots = {}
    if not graph_id or type(current_version) is not int or not graph.get("nodes"):
        return RunGraphHistory(projection, snapshots)

    handoff_authority = getattr(runtime, "graph_handoff_authority", None)
    handoff_store = getattr(handoff_authority, "store", None)
    activation_authority = getattr(runtime, "graph_activation_authority", None)
    activation_store = getattr(activation_authority, "store", None)
    handoffs = handoff_store.list_for_run(run.run_id) if handoff_store is not None else ()
    activations = activation_store.activations_for_run(run.run_id) if activation_store is not None else ()
    activated = {}
    for activation in activations:
        if (activation.status != "ACTIVATED_PAUSED" or activation.run_id != run.run_id
                or activation.mission_id != run.mission_id or activation.graph_id != graph_id
                or activation.candidate_graph_version > current_version):
            continue
        if activation.candidate_graph_version in activated:
            raise ValueError("graph history contains conflicting activations")
        activated[activation.candidate_graph_version] = activation
    confirmed = {}
    for handoff in handoffs:
        if (handoff.run_id != run.run_id or handoff.status != "STATE_PREPARED"
                or handoff.graph_version > current_version
                or handoff.identity_link.candidate_graph.graph_id != graph_id):
            continue
        activation = activated.get(handoff.graph_version)
        if (activation is None or activation.status != "ACTIVATED_PAUSED"
                or activation.activation_id != handoff.activation_id
                or activation.run_id != run.run_id or activation.mission_id != run.mission_id
                or activation.graph_id != graph_id or activation.candidate_graph_version != handoff.graph_version
                or activation.package_checksum != handoff.candidate.package_checksum
                or activation.source_kind != handoff.source_kind):
            continue
        if handoff.graph_version in confirmed:
            raise ValueError("graph history contains conflicting handoffs")
        confirmed[handoff.graph_version] = handoff

    blueprint, version_graph, version = current_blueprint, graph, current_version
    while True:
        handoff, activation = confirmed.get(version), activated.get(version)
        proposal = _accepted_revision(runtime, run, activation, version_graph)
        patch = proposal.graph_patch if proposal is not None else None
        if patch is None and version == current_version:
            raw_patch = run.execution_state.get("graphDiff")
            if isinstance(raw_patch, dict):
                candidate_patch = GraphPatch.model_validate(raw_patch)
                if candidate_patch.graph_id == graph_id and candidate_patch.graph_version == version:
                    patch = candidate_patch
        inherited_state = handoff.candidate.state if handoff is not None else {}
        completed = list(inherited_state.get("completedStepIds") or ())
        skipped = list(inherited_state.get("skippedStepIds") or ())
        inherited_nodes = set(completed) | set(skipped)
        predecessor = (_source_snapshot(identity_blueprint, run, activation, proposal)
                       if handoff is None and proposal is not None else None)
        source_id = (handoff.identity_link.source_blueprint_id if handoff is not None else
                     predecessor.blueprint_id if predecessor is not None else None)
        item = {"blueprintId": blueprint.blueprint_id if blueprint else None,
            "graphId": graph_id, "graphVersion": version,
            "taskPlanVersion": (blueprint.metadata.get("plannerPlanVersion") if blueprint else
                                run.execution_state.get("taskPlanVersion") if version == current_version else None),
            "current": version == current_version, "status": "active" if version == current_version else "historical",
            "createdAt": blueprint.created_at.isoformat() if blueprint else None,
            "predecessorBlueprintId": source_id, "reason": patch.reason if patch and patch.reason else None,
            "patch": _patch_projection(patch),
            "inherited": {"completedStepIds": completed, "skippedStepIds": skipped,
                "attemptIds": list((*handoff.identity_link.prefix_attempt_ids, *handoff.identity_link.retained_attempt_ids))
                    if handoff is not None else [],
                "outputRefs": {key: value for key, value in (inherited_state.get("outputRefs") or {}).items()
                               if key in inherited_nodes}},
            "activationId": activation.activation_id if activation else None,
            "handoffId": handoff.handoff_id if handoff else None}
        projection["items"].append(item)
        if blueprint is not None:
            snapshots[blueprint.blueprint_id] = {"runId": run.run_id, "blueprintId": blueprint.blueprint_id,
                "missionId": run.mission_id, "graphId": graph_id, "graphVersion": version,
                "taskPlanVersion": item["taskPlanVersion"], "historical": version != current_version,
                "nodes": list(version_graph.get("nodes") or ()), "edges": list(version_graph.get("edges") or ()),
                "source": "agentos-v2"}
        if source_id is None or repositories is None:
            break
        predecessor = predecessor or repositories.blueprints.get(source_id)
        source_graph = handoff.identity_link.source_graph if handoff is not None else None
        if (predecessor is None or predecessor.mission_id != run.mission_id
                or predecessor.graph_id != graph_id or _version(predecessor.graph) != version - 1
                or (handoff is not None and (source_graph is None or source_graph.graph_id != graph_id
                    or str(_version(predecessor.graph)) != source_graph.version))):
            raise ValueError("graph predecessor differs from its confirmed handoff")
        blueprint, version_graph, version = predecessor, predecessor.graph, version - 1
    projection["items"].reverse()
    return RunGraphHistory(projection, snapshots)
