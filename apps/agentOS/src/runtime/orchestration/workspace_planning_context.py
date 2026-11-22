"""Reference-only observations and causal workspace material delivery."""
from __future__ import annotations

from copy import copy
from types import SimpleNamespace

from contracts import stable_checksum
from contracts.execution_evidence import _current_records, _verified_receipts
from contracts.workspace_planning import workspace_planning_phase


def _selected_steps(run, phase):
    completed = {step.step_id: step for step in run.steps
                 if step.step_id in run.completed_step_ids and step.status == "completed"}
    discovery = {key for key, step in completed.items() if step.logical_role == "workspace_discovery"}
    if phase == "discovery":
        return [step for step in run.steps if step.step_id in discovery]
    successors, predecessors = {}, {}
    for edge in (run.acg_blueprint or {}).get("edges", ()):
        if edge.get("activation") == "terminated" or edge.get("edgeType", "dependency") != "dependency":
            continue
        successors.setdefault(edge["sourceId"], set()).add(edge["targetId"])
        predecessors.setdefault(edge["targetId"], set()).add(edge["sourceId"])

    def frontier(candidates):
        result = set()
        for step_id in candidates:
            pending, visited = list(successors.get(step_id, ())), set()
            while pending:
                target = pending.pop()
                if target in visited:
                    continue
                visited.add(target)
                if target in candidates:
                    break
                pending.extend(successors.get(target, ()))
            else:
                result.add(step_id)
        return result

    reviews = frontier({key for key, step in completed.items()
                        if step.logical_role == "workspace_review" or step.capability == "verification"})
    selected = discovery | frontier(set(completed) - discovery) | reviews
    # A review often cites the acquisition immediately before it rather than
    # rereading the page. Deliver that actual source alongside its findings.
    selected.update(parent for review in reviews for parent in predecessors.get(review, ())
                    if parent in completed and completed[parent].capability == "information_extraction")
    return [step for step in run.steps if step.step_id in selected]


def _source(store, run_id, step_id, reference, commits):
    from runtime.orchestration.planning_results import committed_output_commit

    try:
        commit = committed_output_commit(store, run_id, step_id, reference, commits=commits)
    except ValueError as exc:
        raise ValueError("workspace context requires one committed audited source") from exc
    if commit.get("auditOutcome") != "allow":
        raise ValueError("workspace context requires one committed audited source")
    return commit, store.get_output(run_id=run_id, output_ref=reference)


def _receipt_key(tool, path, output):
    return tool, path, stable_checksum(output)


def _verified_observations(run, store, records, *, all_records=None):
    all_records = _current_records(run, store) if all_records is None else all_records
    mutations = [record for record in all_records if record.get("tool") in {"fs.write", "fs.patch", "shell.exec"}]
    verified = {_receipt_key(tool, path, output) for tool, path, output in _verified_receipts(run, store, all_records)}
    observations, seen = [], set()
    for record in records:
        if record.get("tool") not in {"fs.read", "fs.list"}:
            continue
        ref = record.get("receiptRef")
        owner = record.get("_evidenceOwnerRunId", run.run_id)
        if not ref or (owner, ref) in seen:
            continue
        # Verify this exact committed record's Request/Receipt association. The
        # global intersection also removes evidence invalidated by later writes.
        for tool, path, output in _verified_receipts(run, store, [record, *mutations]):
            if _receipt_key(tool, path, output) in verified:
                observations.append({"tool": tool, "path": path, "receiptRef": ref, "output": output})
                seen.add((owner, ref))
    return observations


def validate_workspace_scope_sources(run, store, policy) -> None:
    """Require one real current source; other caller references remain allowed.

    This reads only the admitted Run's immutable evidence. It neither evaluates
    the proposed business rationale nor invokes a filesystem or model tool.
    """
    refs = policy.get("sourceRefs") if isinstance(policy, dict) else None
    if not isinstance(refs, (list, tuple)) or not refs or any(not isinstance(ref, str) for ref in refs):
        raise ValueError("workspace scope sourceRefs require at least one current committed source")
    requested = set(refs)
    commits = store.list_node_commits(run_id=run.run_id)
    outputs = run.execution_state.get("outputRefs") or {}
    for step in run.steps:
        ref = outputs.get(step.step_id)
        if step.step_id in run.completed_step_ids and step.status == "completed" and ref in requested:
            _source(store, run.run_id, step.step_id, ref, commits)
            return
    records = _current_records(run, store)
    if any(item["receiptRef"] in requested for item in _verified_observations(run, store, records, all_records=records)):
        return
    raise ValueError("workspace scope sourceRefs require at least one current committed source")


def workspace_discovery_snapshot(run, store):
    """Seal stable discovery plus the latest causal evidence outside Run state."""
    plan = run.execution_state.get("taskPlan") or {}
    phase = workspace_planning_phase(plan)
    if phase is None:
        return None
    policy = plan["metadata"]["workspaceDiscovery"]
    steps = _selected_steps(run, phase)
    refs = run.execution_state.get("outputRefs") or {}
    commits = store.list_node_commits(run_id=run.run_id) if steps else ()
    sources = []
    for step in steps:
        ref = refs.get(step.step_id)
        if not ref:
            continue
        commit, findings = _source(store, run.run_id, step.step_id, ref, commits)
        sources.append({"sourceRef": ref, "stepId": step.step_id, "commitId": commit["commitId"],
                        "role": step.logical_role, "findings": findings})
    snapshot = {"version": 1, "phase": phase, "scopeOrigin": policy["scopeOrigin"],
                "sourceRefs": [item["sourceRef"] for item in sources], "contextRef": None}
    if not sources:
        return snapshot
    selected = copy(run)
    selected.steps = steps
    selected.execution_state = {**run.execution_state, "outputRefs": {
        item["stepId"]: item["sourceRef"] for item in sources}}
    records = _current_records(selected, store)
    observations = _verified_observations(run, store, records)
    material = {"version": 1, "runId": run.run_id, "phase": phase,
                "sources": sources, "observations": observations}
    digest = stable_checksum(material)
    owner_step = sources[0]["stepId"]
    ref = store.put_tool_value(run_id=run.run_id, step_id=owner_step,
        key="workspace-discovery-context:" + digest, payload=material)
    return {**snapshot, "contextRef": ref, "contextStepId": owner_step, "contextChecksum": digest,
            "verifiedObservationCount": len(observations)}


def load_workspace_discovery_materials(store, observation):
    """Resolve exactly the sealed sources; never scan or collect newer bodies."""
    snapshot = observation.workspace_discovery
    if not snapshot or not snapshot.get("contextRef"):
        raise ValueError("workspace planning requires committed discovery material")
    if snapshot.get("contextStepId"):
        store.assert_reference(kind="output", run_id=observation.run_id, step_id=snapshot["contextStepId"],
                               reference=snapshot["contextRef"])
    material = store.get_output(run_id=observation.run_id, output_ref=snapshot["contextRef"])
    if (material.get("version") != 1 or material.get("runId") != observation.run_id
            or material.get("phase", snapshot.get("phase")) != snapshot.get("phase")
            or stable_checksum(material) != snapshot.get("contextChecksum")
            or [item["sourceRef"] for item in material.get("sources", ())] != snapshot["sourceRefs"]):
        raise ValueError("workspace planning context identity changed")
    commits = store.list_node_commits(run_id=observation.run_id)
    for source in material["sources"]:
        if "phase" in material and ("stepId" not in source or "commitId" not in source):
            raise ValueError("workspace planning source provenance missing")
        if "stepId" in source:
            commit, findings = _source(store, observation.run_id, source["stepId"], source["sourceRef"], commits)
            if commit["commitId"] != source.get("commitId") or findings != source["findings"]:
                raise ValueError("workspace planning source identity changed")
    if "phase" in material:
        view = SimpleNamespace(run_id=observation.run_id,
            steps=[SimpleNamespace(step_id=item["stepId"]) for item in material["sources"]],
            completed_step_ids=[item["stepId"] for item in material["sources"]],
            execution_state={"outputRefs": {item["stepId"]: item["sourceRef"] for item in material["sources"]}})
        records = _current_records(view, store)
        for item in material["observations"]:
            matches = [record for record in records if record.get("receiptRef") == item.get("receiptRef")
                       and record.get("tool") == item.get("tool")]
            if not matches:
                raise ValueError("workspace planning observation lacks its committed source")
            record = matches[0]
            owner = record.get("_evidenceOwnerRunId", observation.run_id)
            store.assert_reference(kind="output", run_id=owner, step_id=record["stepId"], reference=item["receiptRef"])
            receipt = store.get_output(run_id=owner, output_ref=item["receiptRef"])
            if (receipt.get("checksum") != record.get("receiptChecksum")
                    or stable_checksum({key: value for key, value in receipt.items() if key != "checksum"}) != receipt.get("checksum")
                    or receipt.get("output") != item.get("output") or item["path"] != receipt["output"].get("path")):
                raise ValueError("workspace planning observation identity changed")
    rejection = observation.planning_commit_rejection
    reference = rejection.get("proposalRef") if isinstance(rejection, dict) else None
    # Old feedback retained only a checksum. It has no resolvable body and
    # must not be reinterpreted as a store reference.
    if isinstance(reference, str) and reference.startswith("graph-patch:"):
        store.assert_reference(kind="graph-patch", run_id=observation.run_id,
                               step_id="__graph__", reference=reference)
        proposal = store.get_graph_patch(run_id=observation.run_id, patch_ref=reference)
        if (proposal.get("version") != 1 or proposal.get("observationId") != rejection.get("observationId")
                or proposal.get("sourceGraphVersion") != observation.graph_version
                or proposal.get("rejection") != {key: rejection.get(key) for key in ("code", "reason")}):
            raise ValueError("workspace rejected proposal identity changed")
        # A rejected candidate can be invalid under the current schema. Its
        # sealed boundary, rather than acceptance validation, governs diagnostic
        # access; otherwise the model cannot inspect what it needs to correct.
        patch = proposal.get("patch")
        if (not isinstance(patch, dict) or patch.get("missionId") != observation.mission_id
                or patch.get("basePlanVersion") != observation.plan_version):
            raise ValueError("workspace rejected proposal targets a different plan")
        return {**material, "rejectedProposal": proposal}
    return material
