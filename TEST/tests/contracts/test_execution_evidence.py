"""Workspace completion requires current, correlated, complete tool evidence.

These offline tests use the real immutable SQLite value/commit store. They do
not execute a workspace tool or infer a successful read from model prose.
"""
from copy import deepcopy
from uuid import NAMESPACE_URL, uuid5

import pytest

from adapters.tool.hands_http import receipt_checksum
from components.executor.value_store import SQLiteExecutionValueStore
from components.planner.intent_analyzer import IntentParser, _PROFILE_SCHEMA
from contracts.execution_evidence import (
    WorkspaceObservationRequirement,
    _is_scoped_observation,
    _progress,
    evaluate_run_workspace_observations,
    freeze_workspace_observations,
    node_workspace_acquisition_progress,
    node_workspace_observation_feedback,
    verified_node_workspace_receipts,
    workspace_coverage_fingerprint,
    workspace_observation_progress,
    workspace_observation_requirements,
    workspace_execution_context,
    workspace_requirement_contains_path,
)
from contracts import stable_checksum
from contracts.workflow import RuntimeRunRecord, StepStatus, WorkflowStep
from contracts.acg.semantic_profile import TaskSemanticProfile
from types import SimpleNamespace


class EvidenceRun:
    def __init__(self, store, run_id="evidence-run"):
        self.store = store
        self.run = RuntimeRunRecord(
            runId=run_id, missionId="mission", workflowId="workflow",
            domain="general", runtimeEngine="acg",
            input={"workspaceBinding": {"workspaceId": "workspace", "grantId": "grant"}},
        )
        self.serial = 0

    def require(self, *requirements):
        freeze_workspace_observations(self.run, requirements)
        return self

    def commit(self, *calls, step_id="reader", current=True, completed=True,
               audit="allow", payload=None, reused_from=None):
        self.serial += 1
        commit_id = f"{self.run.run_id}:commit-{self.serial}"
        if not any(step.step_id == step_id for step in self.run.steps):
            self.run.steps.append(WorkflowStep(
                stepId=step_id, name=step_id, agentName="offline",
                capability="information_extraction", status=StepStatus.COMPLETED,
            ))
        records = [self.record(step_id, commit_id, i, call) for i, call in enumerate(calls)]
        output_ref = self.store.put_output(run_id=self.run.run_id, step_id=step_id,
            payload=payload or {"claimedRead": True, "records": records})
        self.store.prepare_node_commit(run_id=self.run.run_id, commit_id=commit_id)
        body = {"outputRef": output_ref, "auditOutcome": audit, "toolCalls": records}
        if reused_from:
            body["reusedFromRunId"] = reused_from[0]
            body["reusedFromOutputRef"] = reused_from[1]
        self.store.complete_node_commit(run_id=self.run.run_id, commit_id=commit_id, payload=body)
        if current:
            self.run.execution_state.setdefault("outputRefs", {})[step_id] = output_ref
            if completed and step_id not in self.run.completed_step_ids:
                self.run.completed_step_ids.append(step_id)
        return records

    def record(self, step_id, commit_id, index, call):
        call = deepcopy(call)
        tool, path = call.pop("tool", "fs.read"), call.pop("path", "source.py")
        identity = {"runId": self.run.run_id, "stepId": step_id,
            "attemptId": f"attempt-{self.serial}", "commitId": commit_id}
        invocation_id = f"{self.run.run_id}:invocation-{self.serial}-{index}"
        execution_id = f"xhexec_{self.serial:08x}{index:08x}"
        request = {"requestId": f"request-{self.serial}-{index}", "resourceId": "resource",
            "invocationId": invocation_id, "capabilityId": tool,
            "idempotencyKey": invocation_id,
            "authorization": {"workspaceId": "workspace", "grantId": "grant"},
            "input": {"path": path}}
        request.update(call.pop("request", {}))
        wal = {"request": request, "identity": identity}
        wal.update(call.pop("wal", {}))
        request_ref = self.store.put_tool_value(run_id=self.run.run_id, step_id=step_id,
            key=invocation_id + ":request", payload=wal)
        if tool == "fs.list":
            output = {"path": path, "entries": []}
        else:
            text = call.pop("text", "真实 source")
            output = {"path": path, "text": text, "bytes": len(text.encode("utf-8"))}
        output.update(call.pop("output", {}))
        for key in call.pop("omit_output", ()):
            output.pop(key, None)
        # Hands derives the wire request ID from the idempotency key; its
        # receipt must match that ID rather than the caller's WAL request ID.
        receipt = {"protocolVersion": "1", "requestId": str(uuid5(NAMESPACE_URL, invocation_id)),
            "invocationId": invocation_id, "capabilityId": tool, "grantId": "grant",
            "idempotencyKey": invocation_id, "identity": identity,
            "status": "completed", "output": output,
            "startedAt": call.pop("started", "2026-11-16T01:00:01+00:00"),
            "completedAt": call.pop("ended", "2026-11-16T01:00:02+00:00")}
        receipt.update(call.pop("receipt", {}))
        receipt["checksum"] = receipt_checksum(receipt)
        if call.pop("corrupt_checksum", False):
            receipt["checksum"] = "forged"
        receipt_ref = self.store.put_tool_value(run_id=self.run.run_id, step_id=step_id,
            key=invocation_id + ":receipt", payload=receipt)
        record = {"tool": tool, "status": "completed", "executionId": execution_id,
            "requestRef": request_ref, "receiptRef": receipt_ref,
            "receiptChecksum": receipt["checksum"], "workspaceId": "workspace", "resourceId": "resource",
            "grantId": "grant", **identity}
        record.update(call.pop("record", {}))
        assert not call, f"unknown test configuration: {call}"
        return record

    def progress(self):
        return workspace_observation_progress(self.run, self.store)

    def blockers(self):
        return evaluate_run_workspace_observations(self.run, self.store)

    def successor(self, run_id="replacement"):
        successor = EvidenceRun(self.store, run_id)
        successor.require(*self.run.execution_state["workspaceObservations"])
        for step in self.run.steps:
            successor.commit(step_id=step.step_id,
                reused_from=(self.run.run_id, self.run.execution_state["outputRefs"][step.step_id]))
        return successor


@pytest.fixture
def evidence(tmp_path):
    store = SQLiteExecutionValueStore(db_path=tmp_path / "evidence.sqlite3")
    try:
        yield EvidenceRun(store)
    finally:
        store.close()


def test_legacy_run_without_explicit_requirements_is_unchanged(evidence):
    evidence.commit(payload={"noToolCalls": True})
    assert evidence.progress() == ()
    assert evidence.blockers() == ()
    assert workspace_observation_progress(evidence.run, None) == ()


def test_empty_workspace_exclusions_preserve_historical_serialization_and_hash():
    historical = {"path": ".", "kind": "directory", "operation": "read", "recursive": True}
    for raw in (historical, {**historical, "excludePaths": []}):
        requirement = WorkspaceObservationRequirement.model_validate(raw)
        assert requirement.exclude_paths == ()
        assert requirement.model_dump(mode="json", by_alias=True) == historical
        assert stable_checksum(requirement.model_dump(mode="json", by_alias=True)) == stable_checksum(historical)
        assert stable_checksum(requirement) == stable_checksum({"kind": "directory", "recursive": True})


def test_exclusions_have_canonical_literal_prefixes():
    requirement = WorkspaceObservationRequirement(kind="directory", recursive=True,
        excludePaths=[".\\src\\generated\\", "src/generated/deep", "./vendor//deps", "vendor/deps"])
    assert requirement.exclude_paths == ("src/generated", "vendor/deps")
    assert requirement.model_dump(mode="json", by_alias=True)["excludePaths"] == ["src/generated", "vendor/deps"]
    assert WorkspaceObservationRequirement.model_validate_json(requirement.model_dump_json(by_alias=True)) == requirement
    assert not workspace_requirement_contains_path(requirement, "src/generated")
    assert not workspace_requirement_contains_path(requirement, "src/generated/file.py")
    assert workspace_requirement_contains_path(requirement, "src/generated-backup/file.py")
    assert workspace_requirement_contains_path(requirement, "vendor/deps.py")


@pytest.mark.parametrize("path", ["", ".", "./", "..", "a/../b", "/secret", "C:\\secret",
    "\\\\host\\share", "file*", "file?", "a\x00b"])
def test_exclusions_cannot_remove_root_escape_or_use_globs(path):
    with pytest.raises(ValueError):
        WorkspaceObservationRequirement(kind="directory", excludePaths=[path])


@pytest.mark.parametrize("scope", [
    {"kind": "directory", "path": "src", "excludePaths": ["src"]},
    {"kind": "directory", "path": "src", "excludePaths": ["docs"]},
    {"kind": "directory", "path": "src", "excludePaths": ["."]},
    {"kind": "file", "path": "src/main.py", "excludePaths": ["src/main.py/cache"]},
    {"kind": "directory", "excludePaths": "cache"},
    {"kind": "directory", "excludePaths": [None]},
])
def test_exclusions_are_arrays_of_descendants_of_a_directory_scope(scope):
    with pytest.raises(ValueError):
        WorkspaceObservationRequirement.model_validate(scope)


def test_coverage_ignores_explicit_excluded_files_directories_and_links(evidence):
    evidence.require({"kind": "directory", "path": ".", "recursive": True,
        "excludePaths": [".git", ".cache", "external", "secret.txt"]})
    evidence.commit({"tool": "fs.list", "path": ".", "output": {"entries": [
        {"name": ".git", "type": "directory"}, {"name": ".cache", "type": "directory"},
        {"name": "external", "type": "symlink"}, {"name": "secret.txt", "type": "file"},
        {"name": ".gitignore", "type": "file"}, {"name": "main.py", "type": "file"}]}},
        {"path": "main.py"}, {"path": ".git/config"}, {"tool": "fs.list", "path": ".cache"})
    progress = evidence.progress()[0]
    assert progress["missingReads"] == [".gitignore"]
    assert progress["missingListings"] == progress["unsupportedEntries"] == []
    assert progress["verifiedReadCount"] == progress["verifiedListingCount"] == 1
    evidence.commit({"path": ".gitignore"}, step_id="finish")
    assert evidence.blockers() == ()


def test_excluded_observations_cannot_satisfy_scoped_progress_or_change_coverage():
    requirement = WorkspaceObservationRequirement(kind="directory", recursive=True, excludePaths=[".git"])
    before = _progress((requirement,), ())
    receipts = (("fs.list", ".git", {"entries": []}), ("fs.read", ".git/config", {"text": "private"}))
    assert _progress((requirement,), receipts) == before
    assert not any(_is_scoped_observation(requirement, tool, path) for tool, path, _ in receipts)
    assert _is_scoped_observation(requirement, "fs.list", ".")
    assert _is_scoped_observation(requirement, "fs.read", ".gitignore")


def test_full_workspace_scope_never_automatically_excludes_git_or_cache():
    requirement = WorkspaceObservationRequirement(kind="directory", recursive=True)
    progress = _progress((requirement,), (("fs.list", ".", {"entries": [
        {"name": ".git", "type": "directory"}, {"name": ".cache", "type": "directory"}]}),))[0]
    assert progress["missingListings"] == [".cache", ".git"]
    assert "excludePaths" not in progress


def test_exclusion_in_one_requirement_cannot_erase_an_independent_file_obligation():
    requirements = (WorkspaceObservationRequirement(kind="directory", excludePaths=["secret.txt"]),
        WorkspaceObservationRequirement(kind="file", path="secret.txt"))
    progress = _progress(requirements, (("fs.list", ".", {"entries": [
        {"name": "secret.txt", "type": "file"}]}),))
    assert progress[0]["complete"] is True
    assert progress[1]["missingReads"] == ["secret.txt"]


def test_accepted_inferred_scope_controls_context_coverage_and_local_acquisition_feedback(evidence):
    from contracts.planning import PlannedTask, TaskImplementationBinding, TaskPlan

    evidence.require({"kind": "directory", "path": ".", "recursive": True})
    frozen = deepcopy(evidence.run.execution_state["workspaceObservations"])
    evidence.commit({"tool": "fs.list", "path": ".", "output": {"entries": [
        {"name": ".git", "type": "directory"}, {"name": "source.py", "type": "file"}]}}, step_id="list-root")
    requirement = {**frozen[0], "excludePaths": [".git"]}
    evidence.run.mission_id = "mission_aabbccddeeff"
    task = PlannedTask(key="acquire", title="Read source", objective="Read this accepted source page",
        capabilityRequirements=("information_extraction",), logicalRole="workspace_acquisition",
        constraints=[{"workspaceReview": {"targets": [{"operation": "read", "path": "source.py"}]}}])
    plan = TaskPlan(missionId=evidence.run.mission_id, nodes=(task,), metadata={
        "workspaceDiscovery": {"version": 1, "phase": "formal", "scopeOrigin": "inferred"},
        "workspaceScope": {"version": 1, "requirements": [requirement], "rationale": "Review source code"}})
    binding = TaskImplementationBinding(planNodeKey=task.key, acgNodeId="active-reader")
    evidence.run.execution_state.update(taskPlan=plan.model_dump(mode="json", by_alias=True),
        taskBindings=[binding.model_dump(mode="json", by_alias=True)])
    context = SimpleNamespace(run=evidence.run,
        step=SimpleNamespace(step_id="active-reader", capability="information_extraction"))

    assert workspace_execution_context(evidence.run)["observationRequirements"] == [requirement]
    assert evidence.progress()[0]["missingListings"] == []
    assert evidence.progress()[0]["missingReads"] == ["source.py"]
    excluded = evidence.record("active-reader", "pending", 40, {"path": ".git/config"})
    assert node_workspace_observation_feedback(context, evidence.store, [excluded])
    source = evidence.record("active-reader", "pending", 41, {"path": "source.py"})
    assert node_workspace_observation_feedback(context, evidence.store, [source]) is None
    progress = node_workspace_acquisition_progress(context, evidence.store, [source])
    assert progress["batchComplete"] is True
    assert progress["remainingScope"][0]["complete"] is True
    assert progress["remainingScope"][0]["excludePaths"] == [".git"]
    assert evidence.run.execution_state["workspaceObservations"] == frozen


@pytest.mark.parametrize("protection", ["legacy", "explicit-origin", "explicit-input"])
def test_scope_metadata_cannot_shrink_legacy_or_explicit_workspace_obligations(evidence, protection):
    evidence.require({"kind": "directory", "path": ".", "recursive": True})
    frozen = deepcopy(evidence.run.execution_state["workspaceObservations"])
    metadata = {"workspaceScope": {"version": 1,
        "requirements": [{**frozen[0], "excludePaths": [".git"]}], "rationale": "Review source code"}}
    if protection != "legacy":
        metadata["workspaceDiscovery"] = {"version": 1, "phase": "formal",
            "scopeOrigin": "explicit" if protection == "explicit-origin" else "inferred"}
    if protection == "explicit-input":
        evidence.run.input["workspaceObservations"] = deepcopy(frozen)
    evidence.run.execution_state["taskPlan"] = {"metadata": metadata}
    evidence.commit({"tool": "fs.list", "path": ".", "output": {"entries": [
        {"name": ".git", "type": "directory"}]}})
    assert workspace_execution_context(evidence.run)["observationRequirements"] == frozen
    assert evidence.progress()[0]["missingListings"] == [".git"]
    assert evidence.run.execution_state["workspaceObservations"] == frozen


def test_every_explicit_workspace_scope_survives_profile_freeze_and_runtime_observation(evidence):
    from contracts.runtime_planning import RuntimePlanningObservation

    raw = [{"kind": "file", "path": f"source-{index:03}.py"} for index in range(96)]
    profile = TaskSemanticProfile(workspaceObservations=raw)
    assert len(profile.workspace_observations) == 96
    evidence.require(*raw)
    progress = evidence.progress()
    assert len(progress) == len(evidence.blockers()) == 96
    assert {item["path"] for item in progress} == {item["path"] for item in raw}
    observation = RuntimePlanningObservation(missionId="mission", runId=evidence.run.run_id,
        graphId="graph", graphVersion=1, planVersion=1, wakeReason="resume", goal="Read sources",
        steps=(), remainingStepIds=(), workspaceObservations=progress)
    restored = RuntimePlanningObservation.model_validate_json(observation.model_dump_json())
    assert restored.workspace_observations == progress


def test_workspace_context_projects_frozen_relative_addressing_without_authority_secrets(evidence):
    evidence.require({"kind": "directory", "path": ".", "operation": "list", "recursive": True})
    evidence.run.input["workspaceBinding"].update(
        workspaceRoot="C:/private/host-project", resourceId="private-resource", risk="private host metadata")
    context = workspace_execution_context(evidence.run)
    assert context == {"status": "bound", "root": ".", "pathMode": "workspace-relative",
        "observationRequirements": [{"kind": "directory", "path": ".", "operation": "list", "recursive": True}]}
    assert "grant" not in str(context) and "private" not in str(context)
    context["observationRequirements"][0]["path"] = "different"
    assert evidence.run.execution_state["workspaceObservations"][0]["path"] == "."


@pytest.mark.parametrize("binding", [None, {}, {"workspaceId": "workspace"},
    {"workspaceId": "workspace", "grantId": "grant", "revoked": True}])
def test_missing_or_revoked_workspace_is_not_presented_as_bound(evidence, binding):
    evidence.require({"kind": "file", "path": "source.py"})
    if binding is None:
        evidence.run.input.pop("workspaceBinding")
    else:
        evidence.run.input["workspaceBinding"] = binding
    context = workspace_execution_context(evidence.run)
    assert context["status"] == "unbound" and context["root"] is None
    assert context["observationRequirements"][0]["path"] == "source.py"


def test_model_claim_and_saved_receipts_without_committed_calls_do_not_count(evidence):
    evidence.require({"kind": "file", "path": "source.py"})
    # A genuine receipt in the WAL and a model-written output field still do
    # not place the operation in the immutable current commit's toolCalls.
    records = evidence.record("reader", "not-a-current-commit", 0, {})
    evidence.commit(payload={"readAllFiles": True, "toolCalls": [records]})
    assert evidence.progress()[0]["missingReads"] == ["source.py"]
    assert evidence.blockers() == ("workspace_observation_incomplete:0",)


def test_current_upstream_read_satisfies_final_that_does_not_call_tools(evidence):
    evidence.require({"kind": "file", "path": "source.py"})
    evidence.commit({"path": "source.py"}, step_id="extract")
    evidence.commit(step_id="final", payload={"report": "uses extraction"})
    assert evidence.progress()[0]["complete"]
    assert evidence.blockers() == ()


@pytest.mark.parametrize("call", [
    {"path": "other.py"},
    {"record": {"workspaceId": "other-workspace"}},
    {"record": {"grantId": "other-grant"}},
    {"receipt": {"grantId": "other-grant"}},
    {"request": {"authorization": {"workspaceId": "other-workspace", "grantId": "grant"}}},
    {"request": {"input": {"path": "other.py"}}},
    {"request": {"capabilityId": "fs.list"}},
    {"request": {"invocationId": "other-execution"}},
    {"request": {"idempotencyKey": "other-operation"}},
    {"request": {"resourceId": "other-resource"}},
    {"record": {"resourceId": "other-resource"}},
    {"receipt": {"requestId": "unrelated-request"}},
    {"receipt": {"invocationId": "unrelated-invocation"}},
    {"receipt": {"idempotencyKey": "unrelated-operation"}},
    {"receipt": {"capabilityId": "fs.list"}},
    {"wal": {"identity": {"runId": "other-run"}}},
    {"record": {"runId": "other-run"}},
    {"record": {"attemptId": "other-attempt"}},
    {"record": {"commitId": "other-commit"}},
    {"record": {"stepId": "other-step"}},
    {"record": {"requestRef": "missing"}},
    {"record": {"receiptRef": "missing"}},
    {"record": {"receiptChecksum": "forged"}},
    {"corrupt_checksum": True},
    {"record": {"status": "failed"}},
    {"receipt": {"status": "failed"}},
], ids=lambda call: str(call))
def test_uncorrelated_or_failed_receipts_cannot_meet_file_requirement(evidence, call):
    evidence.require({"kind": "file", "path": "source.py"})
    evidence.commit(call)
    assert evidence.blockers()


def test_hands_execution_id_is_distinct_from_the_correlated_caller_invocation(evidence):
    evidence.require({"kind": "file", "path": "source.py"})
    record = evidence.commit({"path": "source.py"})[0]
    receipt = evidence.store.get_output(run_id=evidence.run.run_id, output_ref=record["receiptRef"])
    request = evidence.store.get_output(run_id=evidence.run.run_id, output_ref=record["requestRef"])["request"]
    assert record["executionId"].startswith("xhexec_")
    assert record["executionId"] != receipt["invocationId"]
    assert request["invocationId"] == receipt["invocationId"]
    assert evidence.blockers() == ()


@pytest.mark.parametrize("reference", ["requestRef", "receiptRef"])
def test_existing_references_from_another_operation_cannot_supply_a_read(evidence, reference):
    evidence.require({"kind": "file", "path": "source.py"})
    other = evidence.commit({"path": "other.py"}, step_id="other-reader")[0]
    evidence.commit({"path": "source.py", "record": {reference: other[reference]}})
    assert evidence.blockers()


@pytest.mark.parametrize("binding", [None, {}, {"workspaceId": "workspace"}, {"grantId": "grant"}])
def test_receipts_need_the_admitted_workspace_and_grant(evidence, binding):
    evidence.require({"kind": "file", "path": "source.py"})
    evidence.commit({})
    evidence.run.input["workspaceBinding"] = binding
    assert evidence.blockers()


@pytest.mark.parametrize("call", [
    {"output": {"partial": True}}, {"output": {"truncated": True}},
    {"output": {"nextCursor": "page-2"}}, {"output": {"hasMore": True}},
    {"output": {"complete": False}}, {"output": {"isComplete": False}},
    {"output": {"truncated": 0}}, {"output": {"partial": []}},
    {"output": {"complete": 0}}, {"output": {"nextCursor": ""}},
    {"output": {"bytes": 1}}, {"output": {"bytes": "13"}},
    {"text": "x", "output": {"bytes": True}},
    {"text": "x", "output": {"bytes": 1.0}},
    {"output": {"offset": 42}}, {"output": {"totalBytes": 1000}},
    {"output": {"binary": True}}, {"output": {"text": None}},
    {"started": "2026-11-16T01:00:03+00:00"},
    {"started": "2026-11-16T01:00:01"},
], ids=lambda call: str(call))
def test_partial_binary_malformed_or_invalid_time_reads_do_not_count(evidence, call):
    evidence.require({"kind": "file", "path": "source.py"})
    evidence.commit(call)
    assert evidence.blockers()


def test_read_byte_count_uses_utf8_and_allows_complete_empty_files(evidence):
    evidence.require({"kind": "file", "path": "source.py"}, {"kind": "file", "path": "empty.py"})
    evidence.commit({"text": "中文😀"}, {"path": "empty.py", "text": ""})
    assert evidence.blockers() == ()


def test_directory_read_needs_listing_and_each_immediate_file(evidence):
    evidence.require({"kind": "directory", "path": "src"})
    evidence.commit({"tool": "fs.list", "path": "src", "output": {"entries": [
        {"name": "a.py", "type": "file"}, {"name": "sub", "type": "directory"}]}})
    assert evidence.progress()[0]["missingReads"] == ["src/a.py"]
    evidence.commit({"path": "src/a.py"}, step_id="followup")
    assert evidence.blockers() == ()  # Nonrecursive scope does not inspect sub.


def test_directory_read_without_listing_cannot_prove_coverage(evidence):
    evidence.require({"kind": "directory", "path": "src"})
    evidence.commit({"path": "src/a.py"})
    assert evidence.progress()[0]["missingListings"] == ["src"]


def test_recursive_directory_requires_every_listing_and_file(evidence):
    evidence.require({"kind": "directory", "path": ".", "recursive": True})
    evidence.commit({"tool": "fs.list", "path": ".", "output": {"entries": [
        {"name": "a.py", "type": "file"}, {"name": "src", "type": "directory"}]}},
        {"path": "a.py"})
    assert evidence.progress()[0]["missingListings"] == ["src"]
    evidence.commit({"tool": "fs.list", "path": "src", "output": {"entries": [
        {"name": "b.py", "type": "file"}, {"name": "empty", "type": "directory"}]}},
        {"tool": "fs.list", "path": "src/empty"}, step_id="enumerate")
    assert evidence.progress()[0]["missingReads"] == ["src/b.py"]
    evidence.commit({"path": "src/b.py"}, step_id="supplement")
    assert evidence.blockers() == ()


def test_explicit_list_operation_needs_no_file_contents(evidence):
    evidence.require({"kind": "directory", "path": ".", "operation": "list"})
    evidence.commit({"tool": "fs.list", "path": ".", "output": {"entries": [
        {"name": "a.py", "type": "file"}]}})
    assert evidence.blockers() == ()


@pytest.mark.parametrize("latest_entries,stale_entries,complete", [
    ([{"name": "new.py", "type": "file"}], [], False),
    ([], [{"name": "removed.py", "type": "file"}], True),
])
def test_latest_listing_wins_regardless_of_step_or_commit_order(evidence, latest_entries, stale_entries, complete):
    evidence.require({"kind": "directory", "path": "."})
    evidence.commit({"tool": "fs.list", "path": ".", "output": {"entries": latest_entries},
        "started": "2026-11-16T01:00:03+00:00", "ended": "2026-11-16T01:00:04+00:00"}, step_id="latest")
    evidence.commit({"tool": "fs.list", "path": ".", "output": {"entries": stale_entries}}, step_id="stale")
    assert evidence.progress()[0]["complete"] is complete


def test_conflicting_directory_snapshots_with_equal_timestamp_cannot_prove_scope(evidence):
    evidence.require({"kind": "directory", "path": "."})
    evidence.commit({"tool": "fs.list", "path": ".", "output": {"entries": [
        {"name": "new.py", "type": "file"}]}}, step_id="first")
    evidence.commit({"tool": "fs.list", "path": "."}, step_id="second")
    assert evidence.progress()[0]["unsupportedEntryCount"] == 1
    assert evidence.blockers()


@pytest.mark.parametrize("output", [
    {"entries": [], "partial": True}, {"entries": [], "nextCursor": "next"},
    {"entries": None}, {"entries": "not-a-list"},
    {"entries": [{"name": "../outside", "type": "file"}]},
    {"entries": [{"name": "nested/file", "type": "file"}]},
    {"entries": [{"name": "nested\\file", "type": "file"}]},
    {"entries": [{"name": "C:outside", "type": "file"}]},
    {"entries": [{"name": "..", "type": "directory"}]},
    {"entries": [{"name": ".", "type": "directory"}]},
    {"entries": [{"name": "", "type": "file"}]},
    {"entries": [{"name": "link", "type": "symlink"}]},
    {"entries": [{"name": "link", "type": "junction"}]},
    {"entries": [{"name": "special", "type": "unknown"}]},
    {"entries": [{"name": "missing-type"}]}, {"entries": [None]},
    {"entries": [{"name": "same", "type": "directory"}, {"name": "same", "type": "directory"}]},
    {"entries": [], "offset": 10}, {"entries": [], "totalEntries": 99},
], ids=lambda output: str(output))
def test_incomplete_or_unsafe_directory_results_fail_closed(evidence, output):
    evidence.require({"kind": "directory", "path": ".", "recursive": True})
    evidence.commit({"tool": "fs.list", "path": ".", "output": output})
    assert evidence.blockers()


@pytest.mark.parametrize("path", ["../secret", "a/../secret", "/secret", "C:\\secret", "\\\\host\\share", "file*", "file?", "a\x00b"])
def test_requirement_paths_cannot_escape_or_glob(path):
    with pytest.raises(ValueError):
        WorkspaceObservationRequirement(kind="file", path=path)


def test_scope_normalization_deduplication_and_freeze(evidence):
    raw = [{"kind": "directory", "path": ".\\src\\", "recursive": True}]
    evidence.require(*raw)
    evidence.require({"kind": "directory", "path": "src", "recursive": True})
    with pytest.raises(ValueError, match="changed after initial graph admission"):
        evidence.require({"kind": "directory", "path": "src", "recursive": False})
    with pytest.raises(ValueError, match="changed after initial graph admission"):
        evidence.require()
    assert len(workspace_observation_requirements([raw[0], raw[0]])) == 1
    assert evidence.run.execution_state["workspaceObservations"][0]["recursive"] is True


def test_semantic_replacement_deep_copies_scope_and_next_plan_cannot_erase_it(evidence):
    from runtime.orchestration.semantic_revision import SemanticRevisionService

    evidence.require({"kind": "directory", "path": "src", "recursive": True})
    original = evidence.run.execution_state["workspaceObservations"]
    # A proposed plan's metadata is not the authority for inherited obligations.
    evidence.run.execution_state["taskPlan"] = {"metadata": {"workspaceObservations": []}}
    fresh = SemanticRevisionService._fresh_replacement_execution_state(evidence.run)
    inherited = fresh["workspaceObservations"]
    assert inherited == original
    assert inherited is not original and inherited[0] is not original[0]
    replacement = evidence.run.model_copy(deep=True, update={"execution_state": fresh})
    with pytest.raises(ValueError, match="changed after initial graph admission"):
        freeze_workspace_observations(replacement, [])
    assert replacement.execution_state["workspaceObservations"] == original
    inherited[0]["recursive"] = False
    assert original[0]["recursive"] is True
    original[0]["path"] = "different-source"
    assert inherited[0]["path"] == "src"


@pytest.mark.parametrize("raw", [
    {"kind": "directory", "path": ".", "exclude": ["secret.py"]},
    {"kind": "directory", "path": ".", "recursive": "false"},
    {"kind": "file", "path": "source.py", "operation": "list"},
    {"kind": "file", "path": "source.py", "recursive": True},
])
def test_scope_contract_rejects_exclusions_and_ambiguous_operations(raw):
    with pytest.raises(ValueError):
        workspace_observation_requirements([raw])


def test_new_commit_cannot_reuse_old_attempt_receipts_by_scanning_history(evidence):
    evidence.require({"kind": "file", "path": "source.py"})
    evidence.commit({})
    assert not evidence.blockers()
    evidence.commit(payload={"claimsOldReadIsStillEnough": True})
    assert evidence.blockers()


@pytest.mark.parametrize("options", [{"completed": False}, {"current": False}, {"audit": "review"}])
def test_only_current_completed_allowed_commit_counts(evidence, options):
    evidence.require({"kind": "file", "path": "source.py"})
    evidence.commit({}, **options)
    assert evidence.blockers()


def test_graph_revision_reuses_completed_read_prefix_with_same_frozen_authority(evidence):
    evidence.require({"kind": "directory", "path": "src", "recursive": True})
    evidence.commit({"tool": "fs.list", "path": "src", "output": {"entries": [
        {"name": "source.py", "type": "file"}]}})
    successor = evidence.successor()
    assert successor.progress()[0]["missingReads"] == ["src/source.py"]
    successor.commit({"path": "src/source.py"}, step_id="supplement")
    assert successor.blockers() == ()
    # More than one graph revision still traces to the original immutable
    # observations, rather than accepting model-reported receipt references.
    assert successor.successor("second-replacement").blockers() == ()


@pytest.mark.parametrize("change", [{"grantId": "different-grant"}, {"workspaceId": "different-workspace"}, {"resourceId": "different-resource"}])
def test_graph_revision_cannot_reauthorize_old_receipts_under_new_binding(evidence, change):
    evidence.require({"kind": "file", "path": "source.py"})
    evidence.commit({})
    successor = evidence.successor()
    successor.run.input["workspaceBinding"].update(change)
    assert successor.blockers()


def test_reused_source_record_must_belong_to_original_step(evidence):
    evidence.require({"kind": "file", "path": "source.py"})
    evidence.commit({"record": {"stepId": "another-step"}})
    assert evidence.successor().blockers()


def test_reuse_lineage_must_resolve_to_committed_output_owned_by_same_step(evidence):
    evidence.require({"kind": "file", "path": "source.py"})
    evidence.commit({}, step_id="another-step")
    wrong_step_ref = evidence.run.execution_state["outputRefs"]["another-step"]
    successor = EvidenceRun(evidence.store, "replacement")
    successor.require({"kind": "file", "path": "source.py"})
    successor.commit(reused_from=(evidence.run.run_id, wrong_step_ref))
    with pytest.raises(ValueError):
        successor.blockers()


def test_nonexistent_reuse_lineage_cannot_be_treated_as_evidence(evidence):
    evidence.require({"kind": "file", "path": "source.py"})
    evidence.commit(reused_from=("nonexistent-run", "nonexistent-ref"))
    with pytest.raises(ValueError, match="current immutable node commit"):
        evidence.blockers()


def test_cyclic_reuse_lineage_is_rejected(evidence):
    evidence.require({"kind": "file", "path": "source.py"})
    run = evidence.run
    ref = evidence.store.put_output(run_id=run.run_id, step_id="reader", payload={})
    run.steps.append(WorkflowStep(stepId="reader", name="reader", agentName="offline"))
    run.completed_step_ids.append("reader")
    run.execution_state["outputRefs"] = {"reader": ref}
    evidence.store.prepare_node_commit(run_id=run.run_id, commit_id="cyclic")
    evidence.store.complete_node_commit(run_id=run.run_id, commit_id="cyclic", payload={
        "outputRef": ref, "reusedFromRunId": run.run_id, "reusedFromOutputRef": ref})
    with pytest.raises(ValueError, match="cyclic workspace evidence"):
        evidence.blockers()


@pytest.mark.parametrize("tool", ["fs.write", "fs.patch", "shell.exec"])
@pytest.mark.parametrize("node_status", ["committed", "uncommitted", "conflicting-summary"])
def test_mutation_invalidates_earlier_reads_until_complete_reread(evidence, tool, node_status):
    evidence.require({"kind": "file", "path": "source.py"})
    evidence.commit({}, step_id="first-read")
    call = {"tool": tool, "started": "2026-11-16T01:00:03+00:00", "ended": "2026-11-16T01:00:04+00:00"}
    if node_status == "uncommitted":
        # Hands completed its work, then the process or node failed before publishing output.
        attempt = "commit:evidence-run:mutate:0"
        evidence.store.prepare_node_commit(run_id=evidence.run.run_id, commit_id=attempt)
        mutation = evidence.record("mutate", attempt, 1, call)
        assert evidence.store.get_node_commit(run_id=evidence.run.run_id, commit_id=attempt)["stage"] == "prepared"
    else:
        if node_status == "conflicting-summary":
            call["record"] = {"status": "failed"}
        mutation = evidence.commit(call, step_id="mutate")[0]
    assert evidence.blockers()
    assert evidence.progress()[0]["coverageInvalidation"] == {
        "tool": tool, "receiptRef": mutation["receiptRef"], "completedAt": "2026-11-16T01:00:04+00:00",
        "invalidatedReadCount": 1, "invalidatedListingCount": 0,
        "reasonCode": "WORKSPACE_OBSERVATIONS_INVALIDATED"}
    assert verified_node_workspace_receipts(evidence.run, evidence.store) == ()
    evidence.commit({"started": "2026-11-16T01:00:05+00:00",
        "ended": "2026-11-16T01:00:06+00:00"}, step_id="reread")
    assert evidence.blockers() == ()


def test_unpublished_mutation_follows_reused_prefix_without_crossing_workspace(evidence):
    evidence.require({"kind": "file", "path": "source.py"}, {"kind": "file", "path": "unrelated.py"})
    evidence.commit({}, {"path": "unrelated.py"})
    timing = {"started": "2026-11-16T01:00:03+00:00", "ended": "2026-11-16T01:00:04+00:00"}
    evidence.record("other-workspace", "other-attempt", 2, {"tool": "shell.exec", **timing,
        "request": {"authorization": {"workspaceId": "other", "grantId": "grant-other"}},
        "receipt": {"grantId": "grant-other"}})
    assert evidence.successor().blockers() == ()
    # The recovery copy still points at observations made before this write.
    evidence.record("failed-writer", "writer-attempt", 3, {"tool": "fs.patch", **timing})
    affected, unaffected = evidence.successor("after-write").progress()
    assert not affected["complete"] and affected["coverageInvalidation"]["tool"] == "fs.patch"
    assert unaffected["complete"] and "coverageInvalidation" not in unaffected


def test_invalidation_facts_are_scoped_and_do_not_expose_command_or_source_bodies(evidence):
    evidence.require({"kind": "directory", "path": "src", "recursive": True},
        {"kind": "file", "path": "outside.py"}, {"kind": "directory", "path": "docs"})
    evidence.commit({"tool": "fs.list", "path": "src"},
        {"tool": "fs.list", "path": "src/nested"},
        {"path": "src/a.py", "text": "source-body-secret"}, {"path": "src/a.py"},
        {"path": "src/nested/b.py"}, {"path": "outside.py"})
    mutation = evidence.commit({"tool": "shell.exec", "started": "2026-11-16T01:00:03+00:00",
        "ended": "2026-11-16T01:00:04+00:00", "request": {"input": {"command": "host-command-secret"}},
        "output": {"command": "host-command-secret", "stdout": "shell-output-secret"}}, step_id="shell")[0]
    src, outside, docs = evidence.progress()
    assert src["coverageInvalidation"]["receiptRef"] == mutation["receiptRef"]
    assert src["coverageInvalidation"]["invalidatedReadCount"] == 2
    assert src["coverageInvalidation"]["invalidatedListingCount"] == 2
    assert outside["coverageInvalidation"]["invalidatedReadCount"] == 1
    assert outside["coverageInvalidation"]["invalidatedListingCount"] == 0
    assert "coverageInvalidation" not in docs
    assert all(secret not in repr(evidence.progress())
               for secret in ("host-command-secret", "source-body-secret", "shell-output-secret"))


def test_invalidation_diagnostics_do_not_create_a_new_coverage_frontier(evidence):
    evidence.require({"kind": "file", "path": "source.py"})
    empty = evidence.progress()
    assert "coverageInvalidation" not in empty[0]
    evidence.commit({}, step_id="read")
    assert "coverageInvalidation" not in evidence.progress()[0]
    latest = evidence.commit({"tool": "shell.exec", "started": "2026-11-16T01:00:05+00:00",
        "ended": "2026-11-16T01:00:06+00:00"}, step_id="latest")[0]
    evidence.commit({"tool": "fs.write", "started": "2026-11-16T01:00:03+00:00",
        "ended": "2026-11-16T01:00:04+00:00"}, step_id="earlier-enumerated-last")
    invalidated = evidence.progress()
    assert invalidated[0]["coverageInvalidation"]["receiptRef"] == latest["receiptRef"]
    assert invalidated[0]["coverageFingerprint"] == empty[0]["coverageFingerprint"]
    assert workspace_coverage_fingerprint(invalidated) == workspace_coverage_fingerprint(empty)


def test_read_that_starts_during_mutation_is_identified_as_invalidated(evidence):
    evidence.require({"kind": "file", "path": "source.py"})
    evidence.commit({"started": "2026-11-16T01:00:04+00:00",
        "ended": "2026-11-16T01:00:07+00:00"}, step_id="overlapping-read")
    evidence.commit({"tool": "shell.exec", "started": "2026-11-16T01:00:03+00:00",
        "ended": "2026-11-16T01:00:04+00:00"}, step_id="shell")
    assert evidence.progress()[0]["coverageInvalidation"]["invalidatedReadCount"] == 1
    assert evidence.blockers()


def test_mutation_also_requires_fresh_directory_listing(evidence):
    evidence.require({"kind": "directory", "path": "."})
    evidence.commit({"tool": "fs.list", "path": ".", "output": {"entries": [
        {"name": "source.py", "type": "file"}]}}, {})
    evidence.commit({"tool": "fs.write", "started": "2026-11-16T01:00:03+00:00",
        "ended": "2026-11-16T01:00:04+00:00"}, step_id="mutate")
    evidence.commit({"started": "2026-11-16T01:00:05+00:00",
        "ended": "2026-11-16T01:00:06+00:00"}, step_id="reread")
    assert evidence.progress()[0]["missingListings"] == ["."]


@pytest.mark.parametrize("tool", ["fs.write", "fs.patch"])
def test_file_update_invalidates_only_the_file_and_its_immediate_directory_listing(evidence, tool):
    evidence.require({"kind": "file", "path": "src/changed.py"},
        {"kind": "file", "path": "src/unchanged.py"}, {"kind": "file", "path": "docs/notes.txt"})
    evidence.commit({"tool": "fs.list", "path": "."}, {"tool": "fs.list", "path": "src"},
        {"tool": "fs.list", "path": "src/nested"}, {"tool": "fs.list", "path": "docs"},
        {"path": "src/changed.py"}, {"path": "src/unchanged.py"}, {"path": "docs/notes.txt"})
    evidence.commit({"tool": tool, "path": "src/changed.py", "output": {"operation": "update"},
        "started": "2026-11-16T01:00:03+00:00", "ended": "2026-11-16T01:00:04+00:00"}, step_id="update")

    observed = {(tool, path) for tool, path, _ in verified_node_workspace_receipts(evidence.run, evidence.store)}
    assert observed == {("fs.read", "src/unchanged.py"), ("fs.read", "docs/notes.txt"),
        ("fs.list", "."), ("fs.list", "src/nested"), ("fs.list", "docs")}
    changed, unchanged, docs = evidence.progress()
    assert not changed["complete"] and changed["coverageInvalidation"]["invalidatedReadCount"] == 1
    assert unchanged["complete"] and docs["complete"]
    assert "coverageInvalidation" not in unchanged and "coverageInvalidation" not in docs


@pytest.mark.parametrize("operation", ["create", None])
def test_creating_a_file_or_legacy_write_rechecks_ancestor_listings_but_preserves_other_evidence(evidence, operation):
    evidence.require({"kind": "file", "path": "src/existing.py"})
    evidence.commit({"tool": "fs.list", "path": "."}, {"tool": "fs.list", "path": "src"},
        {"tool": "fs.list", "path": "src/new"}, {"tool": "fs.list", "path": "src/unrelated"},
        {"tool": "fs.list", "path": "docs"}, {"path": "src/existing.py"})
    output = {} if operation is None else {"operation": operation}
    evidence.commit({"tool": "fs.write", "path": "src/new/file.py", "output": output,
        "started": "2026-11-16T01:00:03+00:00", "ended": "2026-11-16T01:00:04+00:00"}, step_id="create")

    assert {(tool, path) for tool, path, _ in verified_node_workspace_receipts(evidence.run, evidence.store)} == {
        ("fs.list", "src/unrelated"), ("fs.list", "docs"), ("fs.read", "src/existing.py")}
    assert evidence.blockers() == ()


@pytest.mark.parametrize("change", [
    {"omit_output": ("path",)}, {"output": {"path": "different.py"}},
    {"output": {"path": "../escape.py"}}, {"path": "."},
    {"output": {"operation": "unrecognized"}},
])
def test_file_mutation_without_correlated_path_remains_unknown_and_invalidates_global_evidence(evidence, change):
    evidence.require({"kind": "file", "path": "source.py"}, {"kind": "file", "path": "unrelated.py"})
    evidence.commit({}, {"path": "unrelated.py"})
    evidence.commit({"tool": "fs.write", "started": "2026-11-16T01:00:03+00:00",
        "ended": "2026-11-16T01:00:04+00:00", **change}, step_id="uncorrelated-write")
    assert all(not item["complete"] and item["coverageInvalidation"] == {
        "status": "unknown", "reasonCode": "WORKSPACE_OBSERVATION_EFFECTS_UNKNOWN"}
        for item in evidence.progress())


def test_normalized_file_mutation_path_matches_the_observed_file(evidence):
    evidence.require({"kind": "file", "path": "src/source.py"})
    evidence.commit({"path": "src/source.py"})
    evidence.commit({"tool": "fs.patch", "path": "src/source.py",
        "request": {"input": {"path": ".\\src\\source.py"}},
        "started": "2026-11-16T01:00:03+00:00", "ended": "2026-11-16T01:00:04+00:00"}, step_id="patch")
    assert evidence.progress()[0]["coverageInvalidation"]["tool"] == "fs.patch"
    assert evidence.blockers()


@pytest.mark.parametrize("tool", ["fs.write", "fs.patch"])
def test_windows_case_alias_mutation_invalidates_original_file_and_parent_listing(evidence, tool):
    evidence.require({"kind": "file", "path": "src/source.py"})
    evidence.commit({"path": "src/source.py"}, {"tool": "fs.list", "path": "src"},
        {"path": "docs/unchanged.py"}, {"tool": "fs.list", "path": "."})
    evidence.commit({"tool": tool, "path": "SRC/SOURCE.PY", "output": {"operation": "update"},
        "started": "2026-11-16T01:00:03+00:00", "ended": "2026-11-16T01:00:04+00:00"}, step_id="update")
    assert {(tool, path) for tool, path, _ in verified_node_workspace_receipts(evidence.run, evidence.store)} == {
        ("fs.read", "docs/unchanged.py"), ("fs.list", ".")}
    progress = evidence.progress()[0]
    assert progress["path"] == "src/source.py" and progress["missingReads"] == ["src/source.py"]
    assert progress["coverageInvalidation"]["invalidatedReadCount"] == 1


def test_case_folding_cannot_prove_read_coverage_or_change_literal_coverage_identity(evidence):
    evidence.require({"kind": "file", "path": "src/source.py"})
    empty = evidence.progress()
    evidence.commit({"path": "SRC/SOURCE.PY"})
    assert evidence.progress() == empty
    assert [(tool, path) for tool, path, _ in verified_node_workspace_receipts(evidence.run, evidence.store)] == [
        ("fs.read", "SRC/SOURCE.PY")]
    evidence.commit({"tool": "fs.patch", "path": "src/source.py",
        "started": "2026-11-16T01:00:03+00:00", "ended": "2026-11-16T01:00:04+00:00"}, step_id="update")
    progress = evidence.progress()
    assert progress[0]["missingReads"] == ["src/source.py"]
    assert progress[0]["coverageFingerprint"] == empty[0]["coverageFingerprint"]
    assert workspace_coverage_fingerprint(progress) == workspace_coverage_fingerprint(empty)


def test_parallel_mutations_use_the_latest_relevant_path_instead_of_the_latest_global_time(evidence):
    evidence.require({"kind": "file", "path": "source.py"}, {"kind": "file", "path": "other.py"})
    evidence.commit({}, {"path": "other.py"}, step_id="initial-read")
    later = evidence.commit({"tool": "fs.patch", "path": "other.py",
        "started": "2026-11-16T01:00:07+00:00", "ended": "2026-11-16T01:00:08+00:00"}, step_id="later")[0]
    earlier = evidence.commit({"tool": "fs.patch", "path": "source.py",
        "started": "2026-11-16T01:00:03+00:00", "ended": "2026-11-16T01:00:04+00:00"}, step_id="earlier")[0]
    source, other = evidence.progress()
    assert source["coverageInvalidation"]["receiptRef"] == earlier["receiptRef"]
    assert other["coverageInvalidation"]["receiptRef"] == later["receiptRef"]
    evidence.commit({"started": "2026-11-16T01:00:05+00:00", "ended": "2026-11-16T01:00:06+00:00"}, step_id="reread")
    source, other = evidence.progress()
    assert source["complete"] and not other["complete"]


def test_repeated_change_to_the_same_file_invalidates_an_intermediate_reread_across_graph_reuse(evidence):
    evidence.require({"kind": "file", "path": "source.py"}, {"kind": "file", "path": "unchanged.py"})
    evidence.commit({}, {"path": "unchanged.py"}, step_id="initial-read")
    evidence.commit({"tool": "fs.patch", "started": "2026-11-16T01:00:03+00:00",
        "ended": "2026-11-16T01:00:04+00:00"}, step_id="first-change")
    evidence.commit({"started": "2026-11-16T01:00:05+00:00", "ended": "2026-11-16T01:00:06+00:00"},
        step_id="intermediate-read")
    later = evidence.commit({"tool": "fs.patch", "started": "2026-11-16T01:00:07+00:00",
        "ended": "2026-11-16T01:00:08+00:00"}, step_id="second-change")[0]
    successor = evidence.successor()
    source, unchanged = successor.progress()
    assert not source["complete"] and unchanged["complete"]
    assert source["coverageInvalidation"]["receiptRef"] == later["receiptRef"]
    successor.commit({"started": "2026-11-16T01:00:09+00:00", "ended": "2026-11-16T01:00:10+00:00"},
        step_id="fresh-read")
    assert successor.blockers() == ()


def test_model_claimed_update_cannot_suppress_directory_creation_effects(evidence):
    evidence.require({"kind": "directory", "path": ".", "operation": "list"})
    evidence.commit({"tool": "fs.list", "path": "."})
    evidence.commit({"tool": "fs.write", "path": "new/source.py",
        "request": {"input": {"path": "new/source.py", "operation": "update"}},
        "started": "2026-11-16T01:00:03+00:00", "ended": "2026-11-16T01:00:04+00:00"}, step_id="write")
    assert evidence.progress()[0]["missingListings"] == ["."]
    assert evidence.progress()[0]["coverageInvalidation"]["invalidatedListingCount"] == 1


@pytest.mark.parametrize("started,ended,complete", [
    ("2026-11-16T01:00:02+00:00", "2026-11-16T01:00:03+00:00", False),
    ("2026-11-16T01:00:03+00:00", "2026-11-16T01:00:06+00:00", False),
    ("2026-11-16T01:00:04+00:00", "2026-11-16T01:00:06+00:00", False),
    ("2026-11-16T01:00:05+00:00", "2026-11-16T01:00:06+00:00", True),
])
def test_path_mutation_requires_observation_to_start_after_its_completion(evidence, started, ended, complete):
    evidence.require({"kind": "file", "path": "source.py"})
    evidence.commit({"started": started, "ended": ended}, step_id="read")
    evidence.commit({"tool": "fs.patch", "started": "2026-11-16T01:00:03+00:00",
        "ended": "2026-11-16T01:00:04+00:00"}, step_id="patch")
    assert evidence.progress()[0]["complete"] is complete


def test_shell_with_success_or_read_only_claim_still_invalidates_all_earlier_paths(evidence):
    evidence.require({"kind": "file", "path": "source.py"}, {"kind": "file", "path": "other.py"})
    evidence.commit({}, {"path": "other.py"})
    evidence.commit({"tool": "shell.exec", "request": {"input": {"command": "Get-ChildItem", "readOnly": True}},
        "output": {"exitCode": 0, "readOnly": True}, "started": "2026-11-16T01:00:03+00:00",
        "ended": "2026-11-16T01:00:04+00:00"}, step_id="shell")
    assert all(not item["complete"] and item["coverageInvalidation"]["tool"] == "shell.exec"
               for item in evidence.progress())


@pytest.mark.parametrize("change", [{"receipt": {"status": "failed"}}, {"corrupt_checksum": True}])
def test_failed_or_unverified_mutation_cannot_leave_prior_read_coverage_valid(evidence, change):
    evidence.require({"kind": "file", "path": "source.py"})
    evidence.commit({}, step_id="first-read")
    evidence.commit({"tool": "fs.write", "started": "2026-11-16T01:00:03+00:00",
        "ended": "2026-11-16T01:00:04+00:00", **change}, step_id="uncertain-mutation")
    assert evidence.blockers()
    assert evidence.progress()[0]["coverageInvalidation"] == {
        "status": "unknown", "reasonCode": "WORKSPACE_OBSERVATION_EFFECTS_UNKNOWN"}


def test_local_agent_feedback_requires_scoped_progress_and_accepts_supplement(evidence):
    evidence.require({"kind": "file", "path": "source.py"})
    context = SimpleNamespace(run=evidence.run,
        step=SimpleNamespace(capability="information_extraction"))
    assert "requirements remain unmet" in node_workspace_observation_feedback(context, evidence.store, [])
    unrelated = evidence.record("reader", "pending-commit", 0, {"path": "other.py"})
    assert node_workspace_observation_feedback(context, evidence.store, [unrelated])
    scoped = evidence.record("reader", "pending-commit", 1, {})
    assert node_workspace_observation_feedback(context, evidence.store, [scoped]) is None
    context.step.capability = "analysis"
    assert node_workspace_observation_feedback(context, evidence.store, []) is None


def test_local_agent_may_make_partial_progress_for_acg_to_decompose_remaining_reading(evidence):
    evidence.require({"kind": "directory", "path": "src"})
    context = SimpleNamespace(run=evidence.run,
        step=SimpleNamespace(capability="information_extraction"))
    listed = evidence.record("reader", "pending-commit", 0, {"tool": "fs.list", "path": "src",
        "output": {"entries": [{"name": "source.py", "type": "file"}]}})
    assert node_workspace_observation_feedback(context, evidence.store, [listed]) is None
    assert evidence.blockers()  # Local progress is not global completion.


@pytest.mark.parametrize("requirement,tool,path,accepted", [
    ({"path": ".", "recursive": True}, "fs.read", "src/source.py", True),
    ({"path": "src"}, "fs.read", "src/source.py", True),
    ({"path": "src"}, "fs.read", "src/nested/source.py", False),
    ({"path": "src", "recursive": True}, "fs.list", "src/nested", True),
    ({"path": "src"}, "fs.list", "src/nested", False),
    ({"path": "src", "recursive": True}, "fs.read", "src-other/source.py", False),
    ({"path": "src", "operation": "list", "recursive": True}, "fs.read", "src/source.py", False),
    ({"path": "src", "operation": "list", "recursive": True}, "fs.list", "src/nested", True),
])
def test_local_batch_may_submit_new_scoped_receipt_before_parent_listing(
        evidence, requirement, tool, path, accepted):
    evidence.require({"kind": "directory", **requirement})
    before = evidence.progress()
    context = SimpleNamespace(run=evidence.run,
        step=SimpleNamespace(capability="information_extraction"))
    record = evidence.record("reader", "pending-commit", 0, {"tool": tool, "path": path})
    feedback = node_workspace_observation_feedback(context, evidence.store, [record])
    assert (feedback is None) is accepted
    evidence.commit({"tool": tool, "path": path})
    # Submitting literal descendants cannot prove that the unlisted directory
    # has no other files, even after the partial node commits successfully.
    assert evidence.progress() == before
    assert evidence.blockers() == ("workspace_observation_incomplete:0",)


@pytest.mark.parametrize("change", [
    {"record": {"status": "failed"}}, {"output": {"partial": True}},
    {"output": {"truncated": True}}, {"output": {"hasMore": True}},
    {"output": {"bytes": 0}}, {"corrupt_checksum": True},
])
def test_local_batch_cannot_submit_incomplete_or_unverified_descendant_read(evidence, change):
    evidence.require({"kind": "directory", "path": "src", "recursive": True})
    context = SimpleNamespace(run=evidence.run,
        step=SimpleNamespace(capability="information_extraction"))
    record = evidence.record("reader", "pending-commit", 0, {"path": "src/source.py", **change})
    assert node_workspace_observation_feedback(context, evidence.store, [record])


def test_local_batch_cannot_repeat_prior_descendant_read_as_new_progress(evidence):
    evidence.require({"kind": "directory", "path": "src", "recursive": True})
    evidence.commit({"path": "src/source.py"})
    context = SimpleNamespace(run=evidence.run,
        step=SimpleNamespace(capability="information_extraction"))
    repeated = evidence.record("supplement", "pending-commit", 99, {"path": "src/source.py"})
    assert node_workspace_observation_feedback(context, evidence.store, [repeated])
    new = evidence.record("supplement", "pending-commit", 100, {"path": "src/other.py"})
    assert node_workspace_observation_feedback(context, evidence.store, [new]) is None


@pytest.mark.parametrize("model_scope", [[], [{"kind": "directory", "path": "src", "operation": "list"}]])
def test_explicit_input_obligations_survive_llm_scope_weakening(model_scope):
    class Model:
        def generate_json(self, prompt, schema, **kwargs):
            return {"primaryGoal": "inspect source", "requiredCapabilities": ["information_extraction"],
                "estimatedComplexity": "simple", "evidenceScope": "authorized_sources",
                "webExtraction": "snippets", "workspaceObservations": model_scope}
    explicit = [{"kind": "directory", "path": "src", "recursive": True}]
    profile = IntentParser(llm=Model()).parse(intent="Read the complete source tree",
        task_input={"workspaceObservations": explicit})
    assert profile.workspace_observations == list(workspace_observation_requirements(explicit))


def test_explicit_input_obligations_also_survive_deterministic_parse():
    explicit = [{"kind": "file", "path": "source.py"}]
    profile = IntentParser().parse(intent="read source", use_llm=False,
        task_input={"workspaceObservations": explicit})
    assert profile.workspace_observations == list(workspace_observation_requirements(explicit))


def test_workspace_scope_adds_registered_acquisition_even_if_model_only_requests_analysis():
    class Model:
        def generate_json(self, prompt, schema, **kwargs):
            return {"primaryGoal": "inspect source", "requiredCapabilities": ["analysis"],
                "estimatedComplexity": "simple", "evidenceScope": "authorized_sources",
                "webExtraction": "snippets", "workspaceObservations": []}
    profile = IntentParser(llm=Model()).parse(intent="inspect source",
        task_input={"workspaceObservations": [{"kind": "file", "path": "source.py"}]})
    assert "information_extraction" in profile.required_capabilities
    assert any(item.capability_id == "information_extraction" for item in profile.capability_candidates)


def test_task_input_only_scope_cannot_silently_accept_actual_workspace_obligations():
    class Model:
        calls = 0

        def generate_json(self, prompt, schema, **kwargs):
            self.calls += 1
            return {"primaryGoal": "inspect source", "requiredCapabilities": ["analysis"],
                "estimatedComplexity": "simple", "evidenceScope": "task_input_only",
                "webExtraction": "snippets", "workspaceObservations": []}
    model = Model()
    with pytest.raises(ValueError, match="workspace inspection conflicts with task_input_only"):
        IntentParser(llm=model).parse(intent="inspect source",
            task_input={"workspaceObservations": [{"kind": "file", "path": "source.py"}]})
    assert model.calls == 2  # One contract repair is allowed, then fail closed.


def test_initial_profile_schema_declares_observation_scope_and_operation():
    assert "workspaceObservations" in _PROFILE_SCHEMA["required"]
    schema = _PROFILE_SCHEMA["properties"]["workspaceObservations"]
    assert schema["type"] == "array" and "maxItems" not in schema
    properties = schema["items"]["properties"]
    assert properties["kind"]["enum"] == ["file", "directory"]
    assert properties["operation"]["enum"] == ["read", "list"]
    assert properties["recursive"]["default"] is False
    assert "workspaceObservations" in TaskSemanticProfile.model_json_schema(by_alias=True)["properties"]


def test_coverage_counts_only_verified_reads_and_listings_inside_the_required_scope(evidence):
    evidence.require({"kind": "directory", "path": "src"})
    evidence.commit({"tool": "fs.list", "path": "src", "output": {"entries": [
        {"name": "source.py", "type": "file"}, {"name": "other.py", "type": "file"}]}},
        {"path": "src/source.py"}, {"path": "unrelated.py"})
    progress = evidence.progress()[0]
    assert progress["verifiedReadCount"] == 1 and progress["verifiedListingCount"] == 1
    assert progress["missingReads"] == ["src/other.py"]
    assert len(progress["coverageFingerprint"]) == 64


def test_discovery_outside_visible_gap_page_is_still_scoped_progress(evidence):
    evidence.require({"kind": "directory", "path": ".", "recursive": True})
    evidence.commit({"tool": "fs.list", "path": ".", "output": {"entries": [
        {"name": f"d{i:02}", "type": "directory"} for i in range(17)]}})
    before = evidence.progress()[0]
    context = SimpleNamespace(run=evidence.run, step=SimpleNamespace(capability="information_extraction"))
    listed = evidence.record("supplement", "pending-commit", 99, {"tool": "fs.list", "path": "d16",
        "output": {"entries": [{"name": "child", "type": "directory"}]}})
    # Both the visible first sixteen gaps and the total gap count stay equal.
    # The full-frontier identity still changes, so this useful observation may
    # return to ACG rather than exhausting the Agent's completion feedback.
    assert node_workspace_observation_feedback(context, evidence.store, [listed]) is None
    evidence.commit({"tool": "fs.list", "path": "d16", "output": {"entries": [
        {"name": "child", "type": "directory"}]}}, step_id="supplement")
    after = evidence.progress()[0]
    assert before["missingListings"] == after["missingListings"]
    assert before["missingListingCount"] == after["missingListingCount"] == 17
    assert before["coverageFingerprint"] != after["coverageFingerprint"]


def test_gap_page_exposes_remaining_files_after_verified_prefix_is_committed(evidence):
    evidence.require({"kind": "directory", "path": ".", "recursive": True})
    evidence.commit({"tool": "fs.list", "path": ".", "output": {"entries": [
        {"name": f"file-{i:02}.py", "type": "file"} for i in range(35)]}})
    first = evidence.progress()[0]
    assert len(first["missingReads"]) == 16 and first["missingReadCount"] == 35
    evidence.commit(*({"path": f"file-{i:02}.py"} for i in range(16)), step_id="first-page")
    second = evidence.progress()[0]
    assert second["verifiedReadCount"] == 16 and second["missingReadCount"] == 19
    assert second["missingReads"][0] == "file-16.py" and len(second["missingReads"]) == 16
    assert first["coverageFingerprint"] != second["coverageFingerprint"]


@pytest.mark.parametrize("intent", ["审查整个仓库的代码", "读取项目中的文件内容", "Review the source repository"])
def test_initial_model_list_scope_cannot_weaken_explicit_source_review(intent):
    class Model:
        def generate_json(self, prompt, schema, **kwargs):
            return {"primaryGoal": intent, "requiredCapabilities": ["analysis"],
                "estimatedComplexity": "simple", "evidenceScope": "authorized_sources",
                "webExtraction": "snippets", "workspaceObservations": [
                    {"path": ".", "kind": "directory", "operation": "list"}]}
    profile = IntentParser(llm=Model()).parse(intent=intent)
    assert profile.workspace_observations[0].operation == "read"
    if "审查" in intent or "Review" in intent:
        assert profile.workspace_observations[0].recursive


def test_initial_source_read_promotion_preserves_model_exclusions():
    class Model:
        def generate_json(self, prompt, schema, **kwargs):
            return {"primaryGoal": "review repository", "requiredCapabilities": ["analysis"],
                "estimatedComplexity": "simple", "evidenceScope": "authorized_sources",
                "webExtraction": "snippets", "workspaceObservations": [
                    {"path": ".", "kind": "directory", "operation": "list", "excludePaths": [".git", "build"]}]}
    profile = IntentParser(llm=Model()).parse(intent="Review the source repository")
    requirement = profile.workspace_observations[0]
    assert requirement.operation == "read" and requirement.recursive
    assert requirement.exclude_paths == (".git", "build")


def test_explicit_full_scope_cannot_be_shrunk_by_model_exclusions():
    class Model:
        def generate_json(self, prompt, schema, **kwargs):
            return {"primaryGoal": "review repository", "requiredCapabilities": ["analysis"],
                "estimatedComplexity": "simple", "evidenceScope": "authorized_sources",
                "webExtraction": "snippets", "workspaceObservations": [
                    {"path": ".", "kind": "directory", "recursive": True, "excludePaths": [".git"]}]}
    explicit = [{"path": ".", "kind": "directory", "operation": "read", "recursive": True}]
    profile = IntentParser(llm=Model()).parse(intent="Review the source repository",
        task_input={"workspaceObservations": explicit})
    assert profile.workspace_observations == list(workspace_observation_requirements(explicit))
    assert profile.workspace_observations[0].exclude_paths == ()


def test_repository_review_with_bound_workspace_has_initial_read_scope_even_if_model_omits_it():
    class Model:
        def generate_json(self, prompt, schema, **kwargs):
            return {"primaryGoal": "repository review", "requiredCapabilities": ["analysis"],
                "estimatedComplexity": "simple", "evidenceScope": "authorized_sources",
                "webExtraction": "snippets", "workspaceObservations": []}
    binding = {"workspaceId": "workspace", "grantId": "grant"}
    profile = IntentParser(llm=Model()).parse(intent="审查整个仓库", task_input={"workspaceBinding": binding})
    assert profile.workspace_observations == [WorkspaceObservationRequirement(
        kind="directory", path=".", operation="read", recursive=True)]


def test_explicit_names_only_scope_is_not_promoted_to_source_reading():
    explicit = [{"kind": "directory", "path": ".", "operation": "list", "recursive": True}]
    profile = IntentParser().parse(intent="只列出仓库目录结构，不读取文件内容", use_llm=False,
        task_input={"workspaceObservations": explicit})
    assert profile.workspace_observations == list(workspace_observation_requirements(explicit))
