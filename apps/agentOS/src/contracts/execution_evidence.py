"""Workspace observation requirements and receipt-backed completion checks.

Requirements describe evidence, never permission. Explicit scope is frozen;
inferred scope can follow the formally accepted workspace planning revision.
Only current node commits and correlated Hands receipts count as observations.
Model assertions and arbitrary model-turn/tool WAL scans do not count.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from contracts import stable_checksum


def workspace_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise ValueError("workspace path must be a bounded relative path")
    value = value.replace("\\", "/")
    if value.startswith("/") or any(c in value for c in ':*?\x00\r\n'):
        raise ValueError("workspace path must be relative and literal")
    parts = value.split("/")
    if ".." in parts:
        raise ValueError("workspace path cannot traverse parent directories")
    return "/".join(p for p in parts if p not in {"", "."}) or "."


class WorkspaceObservationRequirement(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True, strict=True)

    path: str = "."
    kind: Literal["file", "directory"]
    operation: Literal["read", "list"] = "read"
    recursive: bool = False
    exclude_paths: tuple[str, ...] = Field(default=(), alias="excludePaths", exclude_if=lambda value: not value)

    _relative_path = field_validator("path")(workspace_relative_path)

    @field_validator("exclude_paths", mode="before")
    @classmethod
    def normalized_exclusions(cls, value):
        if not isinstance(value, (list, tuple)):
            raise ValueError("workspace exclusions must be literal relative paths")
        paths = sorted({workspace_relative_path(path) for path in value})
        # An excluded directory already excludes its descendants. Keep one
        # canonical prefix set instead of hashing redundant representations.
        prefixes = []
        for path in paths:
            if not any(_path_within(path, prefix) for prefix in prefixes):
                prefixes.append(path)
        return tuple(prefixes)

    @model_validator(mode="after")
    def valid_operation(self):
        if self.kind == "file" and (self.operation != "read" or self.recursive or self.path == "."):
            raise ValueError("file observations require one literal file read")
        if self.exclude_paths and (self.kind != "directory" or any(
                path == self.path or not _path_within(path, self.path) for path in self.exclude_paths)):
            raise ValueError("workspace exclusions must be strict descendants of the required directory")
        return self


def _path_within(path, root):
    return root == "." or path == root or path.startswith(root + "/")


def workspace_requirement_contains_path(requirement, path):
    """Match one workspace-relative literal path against an explicit scope."""
    path = workspace_relative_path(path)
    return _path_within(path, requirement.path) and not any(
        _path_within(path, excluded) for excluded in requirement.exclude_paths
    )


class WorkspaceAcquisitionTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    operation: Literal["read", "list"]
    path: str

    _relative_path = field_validator("path")(workspace_relative_path)


_REQUIREMENTS = TypeAdapter(tuple[WorkspaceObservationRequirement, ...])


def workspace_observation_requirements(raw) -> tuple[WorkspaceObservationRequirement, ...]:
    requirements = _REQUIREMENTS.validate_python(() if raw is None else raw)
    return tuple(dict.fromkeys(requirements))


def freeze_workspace_observations(run, raw) -> None:
    """Called at first materialization/activation, never by a revised plan."""
    requirements = workspace_observation_requirements(raw)
    serialized = [r.model_dump(by_alias=True, mode="json") for r in requirements]
    previous = run.execution_state.get("workspaceObservations")
    if previous is not None and previous != serialized:
        raise ValueError("workspace observations changed after initial graph admission")
    run.execution_state["workspaceObservations"] = serialized


def workspace_execution_context(run) -> dict | None:
    """Project addressing and accepted evidence obligations, never host authority.

    Only the runtime-owned Run binding is considered. Tool execution still
    revalidates the live grant; this view neither grants access nor proves a read.
    Host paths, grant identifiers and credentials never enter the model context.
    """
    from contracts.workspace_planning import effective_workspace_requirements

    binding = run.input.get("workspaceBinding")
    requirements = effective_workspace_requirements(run)
    if binding is None and not requirements:
        return None
    bound = (isinstance(binding, dict) and bool(binding.get("workspaceId"))
             and bool(binding.get("grantId")) and not binding.get("revoked", False))
    return {
        "status": "bound" if bound else "unbound",
        "root": "." if bound else None,
        "pathMode": "workspace-relative",
        "observationRequirements": [item.model_dump(by_alias=True, mode="json") for item in requirements],
    }


def _current_records(run, store):
    refs = run.execution_state.get("outputRefs") or {}
    completed = set(run.completed_step_ids)
    records = []
    commits_by_owner = {}

    def collect(owner_id, step_id, ref, visited):
        address = (owner_id, ref)
        if address in visited:
            raise ValueError("cyclic workspace evidence reuse lineage")
        if owner_id not in commits_by_owner:
            commits_by_owner[owner_id] = store.list_node_commits(run_id=owner_id)
        matches = [c for c in commits_by_owner[owner_id]
                   if c.get("stage") == "committed" and c.get("outputRef") == ref]
        if len(matches) != 1:
            raise ValueError("workspace evidence requires one current immutable node commit")
        commit = matches[0]
        store.assert_reference(kind="output", run_id=owner_id, step_id=step_id, reference=ref)
        # Follow only the engine's immutable copied-output lineage. ACG local
        # revision reuses its completed prefix rather than rereading everything.
        # Original receipts still have to match the current frozen workspace.
        if commit.get("reusedFromRunId"):
            if not commit.get("reusedFromOutputRef"):
                raise ValueError("workspace evidence reuse requires its original output reference")
            collect(commit["reusedFromRunId"], step_id, commit["reusedFromOutputRef"], visited | {address})
            return
        if commit.get("auditOutcome") != "allow":
            return
        for record in commit.get("toolCalls") or ():
            if (isinstance(record, dict) and record.get("commitId") == commit.get("commitId")
                    and record.get("stepId") == step_id and record.get("runId") == owner_id):
                records.append({**record, "_evidenceOwnerRunId": owner_id})

    for step in run.steps:
        ref = refs.get(step.step_id)
        if step.step_id in completed and ref:
            collect(run.run_id, step.step_id, ref, frozenset())
    return records


@dataclass(frozen=True)
class _WorkspaceMutation:
    tool: str
    receipt_ref: str
    completed_at: datetime
    completed_at_text: str
    path: str | None = None
    listing_paths: frozenset[str] = frozenset()

    def diagnostic(self):
        return {"tool": self.tool, "receiptRef": self.receipt_ref,
            "completedAt": self.completed_at_text, "reasonCode": "WORKSPACE_OBSERVATIONS_INVALIDATED"}


def _latest_mutation(*mutations):
    return max((item for item in mutations if item is not None),
        key=lambda item: (item.completed_at, item.receipt_ref), default=None)


def _mutation_listing_paths(path, *, include_ancestors):
    directory = path.rpartition("/")[0] or "."
    paths = {directory}
    while include_ancestors and directory != ".":
        directory = directory.rpartition("/")[0] or "."
        paths.add(directory)
    return frozenset(paths)


def _invalidation_path_key(path):
    # Hands currently writes through atomic replacement, so the affected file
    # is this directory entry rather than other hard links to its old inode.
    # Fold only invalidation lookup keys to catch Windows case aliases. Receipt
    # paths and positive coverage checks keep their original literal identity;
    # case-distinct files on other hosts may conservatively need another read.
    return path.casefold()


@dataclass(frozen=True)
class _WorkspaceReceiptEvidence:
    receipts: tuple = ()
    invalidated_receipts: tuple = ()
    invalidation: dict | None = None


def _workspace_receipt_evidence(run, store, records):
    binding = run.input.get("workspaceBinding") or {}
    if not store or not binding.get("workspaceId") or not binding.get("grantId"):
        return _WorkspaceReceiptEvidence()
    receipts, mutations = [], {}
    mutation_refs = {record.get("receiptRef") for record in records
                     if record.get("tool") in {"fs.write", "fs.patch", "shell.exec"}}
    seen = set()
    for record in records:
        if record.get("tool") not in {"fs.read", "fs.list", "fs.write", "fs.patch", "shell.exec"} or record.get("status") != "completed":
            continue
        ref = record.get("receiptRef")
        if not ref or ref in seen:
            continue
        seen.add(ref)
        try:
            owner_id = record.get("_evidenceOwnerRunId", run.run_id)
            store.assert_reference(kind="output", run_id=owner_id, step_id=record["stepId"], reference=ref)
            receipt = store.get_output(run_id=owner_id, output_ref=ref)
            request_ref = record["requestRef"]
            store.assert_reference(kind="output", run_id=owner_id, step_id=record["stepId"], reference=request_ref)
            request_wal = store.get_output(run_id=owner_id, output_ref=request_ref)
            request = request_wal["request"]
            checksum = stable_checksum({k: v for k, v in receipt.items() if k != "checksum"})
            identity = receipt.get("identity") or {}
            if (checksum != receipt.get("checksum") or checksum != record.get("receiptChecksum")
                    or receipt.get("status") != "completed"
                    or receipt.get("capabilityId") != record["tool"]
                    or receipt.get("grantId") != binding["grantId"]
                    or record.get("workspaceId") != binding["workspaceId"]
                    or record.get("grantId") != binding["grantId"]
                    or request.get("authorization") != {"grantId": binding["grantId"], "workspaceId": binding["workspaceId"]}
                    or request.get("capabilityId") != record["tool"]
                    or request.get("invocationId") != receipt.get("invocationId")
                    or request.get("idempotencyKey") != receipt.get("idempotencyKey")
                    or receipt.get("requestId") != str(uuid5(NAMESPACE_URL, request["idempotencyKey"]))
                    or request.get("resourceId") != record.get("resourceId")
                    or (binding.get("resourceId") and binding["resourceId"] != record.get("resourceId"))
                    or request_wal.get("identity") != identity
                    or record.get("runId") != owner_id
                    or any(not record.get(k) or identity.get(k) != record[k]
                           for k in ("runId", "stepId", "attemptId", "commitId"))):
                continue
            # Hands assigns executionId when it admits a request. Its receipt
            # preserves the caller's invocationId instead; they are separate
            # identities. The immutable request/receipt references, checksum
            # and invocation/Attempt correlation above establish this evidence.
            started = datetime.fromisoformat(receipt["startedAt"])
            ended = datetime.fromisoformat(receipt["completedAt"])
            if started.tzinfo is None or ended.tzinfo is None or ended < started:
                continue
            if record["tool"] in {"fs.write", "fs.patch", "shell.exec"}:
                path, listing_paths = None, frozenset()
                if record["tool"] != "shell.exec":
                    output = receipt.get("output") or {}
                    path = workspace_relative_path(output["path"])
                    if path == "." or workspace_relative_path(request["input"]["path"]) != path:
                        continue
                    # A write can create missing parent directories. A patch,
                    # or an explicitly reported update, only changes this file
                    # and its immediate directory entry (which may carry size).
                    if record["tool"] == "fs.write" and "operation" in output and output["operation"] not in {"create", "update"}:
                        continue
                    listing_paths = _mutation_listing_paths(path,
                        include_ancestors=record["tool"] == "fs.write" and output.get("operation") != "update")
                mutations[ref] = _WorkspaceMutation(record["tool"], ref, ended,
                    receipt["completedAt"], path, listing_paths)
                continue
            output = receipt.get("output") or {}
            path = workspace_relative_path(output["path"])
            if workspace_relative_path(request["input"]["path"]) != path:
                continue
            # A successful transport does not make a partial body complete.
            boolean_flags = {"truncated", "partial", "hasMore", "complete", "isComplete"}
            if (any(key in output and type(output[key]) is not bool for key in boolean_flags)
                    or ("nextCursor" in output and output["nextCursor"] is not None)):
                continue
            if (any(output.get(k) for k in ("truncated", "partial", "nextCursor", "hasMore"))
                    or any(output.get(k) is False for k in ("complete", "isComplete"))):
                continue
            flags = boolean_flags | {"nextCursor"}
            if record["tool"] == "fs.read":
                if set(output) - {"path", "text", "content", "bytes", "version", "binary", "encoding"} - flags:
                    continue
                # Binary bytes are an execution fact, not inspected source text.
                if output.get("binary") or not isinstance(output.get("text", output.get("content")), str):
                    continue
                text = output.get("text", output.get("content"))
                if "bytes" in output and (type(output["bytes"]) is not int or output["bytes"] != len(text.encode("utf-8"))):
                    continue
            elif set(output) - {"path", "entries"} - flags or not isinstance(output.get("entries"), list):
                continue
            receipts.append((record["tool"], path, output, started, ended))
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    if mutation_refs != set(mutations):
        # A failed/uncorrelated mutation may have partial effects. It cannot
        # leave earlier read coverage looking current.
        return _WorkspaceReceiptEvidence(invalidation={"status": "unknown",
            "reasonCode": "WORKSPACE_OBSERVATION_EFFECTS_UNKNOWN"})
    global_mutation, file_mutations, listing_mutations = None, {}, {}
    for mutation in mutations.values():
        if mutation.path is None:
            # Arbitrary shell execution has no proven path-local effect.
            global_mutation = _latest_mutation(global_mutation, mutation)
            continue
        path_key = _invalidation_path_key(mutation.path)
        file_mutations[path_key] = _latest_mutation(file_mutations.get(path_key), mutation)
        for path in mutation.listing_paths:
            path_key = _invalidation_path_key(path)
            listing_mutations[path_key] = _latest_mutation(listing_mutations.get(path_key), mutation)
    current, invalidated = [], []
    for item in receipts:
        tool, path, output, started, _ = item
        scoped = file_mutations if tool == "fs.read" else listing_mutations
        mutation = _latest_mutation(global_mutation, scoped.get(_invalidation_path_key(path)))
        if mutation is not None and started <= mutation.completed_at:
            invalidated.append((tool, path, output, mutation))
        else:
            current.append(item)
    # Commit enumeration is not chronological (parallel nodes, retries and
    # reused prefixes). Prefer the most recent complete listing of each path.
    latest_listings = {}
    for tool, path, output, started, ended in current:
        if tool != "fs.list":
            continue
        previous = latest_listings.get(path)
        if previous is None or ended > previous[0]:
            latest_listings[path] = (ended, output)
        elif ended == previous[0] and output != previous[1]:
            # Equally timed conflicting snapshots cannot prove either scope.
            latest_listings[path] = (ended, {"entries": [{"name": ".", "type": "conflict"}]})
    verified = (tuple((tool, path, output) for tool, path, output, *_ in current if tool == "fs.read")
                + tuple(("fs.list", path, output) for path, (_, output) in sorted(latest_listings.items())))
    return _WorkspaceReceiptEvidence(receipts=verified, invalidated_receipts=tuple(invalidated))


def _verified_receipts(run, store, records):
    return _workspace_receipt_evidence(run, store, records).receipts


def verified_node_workspace_receipts(run, store):
    """Return only current, correlated, complete workspace observations."""
    return _verified_receipts(run, store, _current_records(run, store)) if store else ()


def _progress(requirements, receipts):
    reads = {path for tool, path, _ in receipts if tool == "fs.read"}
    listings = {path: output["entries"] for tool, path, output in receipts if tool == "fs.list"}
    progress = []
    for requirement in requirements:
        missing_reads, missing_lists, unsupported = set(), set(), set()
        verified_reads, verified_lists = set(), set()
        if requirement.kind == "file":
            if requirement.path not in reads:
                missing_reads.add(requirement.path)
            else:
                verified_reads.add(requirement.path)
        else:
            pending, visited = [requirement.path], set()
            while pending:
                directory = pending.pop()
                if directory in visited:
                    continue
                visited.add(directory)
                entries = listings.get(directory)
                if entries is None:
                    missing_lists.add(directory)
                    continue
                verified_lists.add(directory)
                names = set()
                for entry in entries:
                    try:
                        name = entry["name"]
                        if not isinstance(name, str) or name in {".", "..", ""} or "/" in name or "\\" in name:
                            raise ValueError("invalid directory entry")
                        path = workspace_relative_path(name if directory == "." else directory + "/" + name)
                        if not workspace_requirement_contains_path(requirement, path):
                            continue
                        if name in names:
                            raise ValueError("duplicate directory entry")
                        names.add(name)
                        kind = entry["type"]
                    except (KeyError, TypeError, ValueError):
                        unsupported.add(directory)
                        continue
                    if kind == "directory":
                        if requirement.recursive:
                            pending.append(path)
                    elif kind == "file":
                        if requirement.operation == "read":
                            if path not in reads:
                                missing_reads.add(path)
                            else:
                                verified_reads.add(path)
                    else:
                        # Symlinks/unknown entries require explicit scope resolution.
                        unsupported.add(path)
        scope = requirement.model_dump(by_alias=True, mode="json")
        # The visible gaps are one work page, never a total-work ceiling. Hash
        # the full frontier so progress outside that page still wakes ACG and
        # cannot be mistaken for a repeated model-only completion candidate.
        fingerprint = stable_checksum({"requirement": scope,
            "missingReads": sorted(missing_reads), "missingListings": sorted(missing_lists),
            "unsupportedEntries": sorted(unsupported),
            "verifiedReads": sorted(verified_reads), "verifiedListings": sorted(verified_lists)})
        progress.append({**scope,
            "complete": not (missing_reads or missing_lists or unsupported),
            "coverageFingerprint": fingerprint,
            "verifiedReadCount": len(verified_reads), "verifiedListingCount": len(verified_lists),
            "missingReads": sorted(missing_reads)[:16], "missingReadCount": len(missing_reads),
            "missingListings": sorted(missing_lists)[:16], "missingListingCount": len(missing_lists),
            "unsupportedEntries": sorted(unsupported)[:16], "unsupportedEntryCount": len(unsupported)})
    return tuple(progress)


def workspace_coverage_fingerprint(progress) -> str:
    """Identity for one host-verified coverage frontier, without receipt bodies."""
    return stable_checksum([item.get("coverageFingerprint") or stable_checksum(item) for item in progress])


def workspace_observation_progress(run, execution_value_store) -> tuple[dict, ...]:
    from contracts.workspace_planning import effective_workspace_requirements

    requirements = effective_workspace_requirements(run)
    if not requirements:
        return ()
    evidence = (_workspace_receipt_evidence(run, execution_value_store,
        _current_records(run, execution_value_store)) if execution_value_store else _WorkspaceReceiptEvidence())
    progress = _progress(requirements, evidence.receipts)
    for requirement, item in zip(requirements, progress):
        if evidence.invalidation:
            item["coverageInvalidation"] = dict(evidence.invalidation)
            continue
        scoped = [(tool, path, mutation) for tool, path, _, mutation in evidence.invalidated_receipts
                  if _is_scoped_observation(requirement, tool, path)]
        if scoped:
            invalidated = {(tool, path) for tool, path, _ in scoped}
            mutation = _latest_mutation(*(mutation for _, _, mutation in scoped))
            # These are unique earlier observations, not a claim that shell
            # wrote a file. Fresh receipts and coverage identities stay separate.
            item["coverageInvalidation"] = {**mutation.diagnostic(),
                "invalidatedReadCount": sum(tool == "fs.read" for tool, _ in invalidated),
                "invalidatedListingCount": sum(tool == "fs.list" for tool, _ in invalidated)}
    return progress


def evaluate_run_workspace_observations(run, execution_value_store) -> tuple[str, ...]:
    return tuple(f"workspace_observation_incomplete:{i}" for i, item in enumerate(
        workspace_observation_progress(run, execution_value_store)) if not item["complete"])


def _is_scoped_observation(requirement, tool, path):
    if not workspace_requirement_contains_path(requirement, path):
        return False
    if requirement.kind == "file":
        return tool == "fs.read" and path == requirement.path
    if path == requirement.path:
        return tool == "fs.list"
    prefix = "" if requirement.path == "." else requirement.path + "/"
    if path == "." or not path.startswith(prefix):
        return False
    relative = path[len(prefix):]
    return (tool == "fs.list" and requirement.recursive
            or tool == "fs.read" and requirement.operation == "read"
            and (requirement.recursive or "/" not in relative))


def _has_new_scoped_observation(requirements, previous, current):
    """A complete acquisition can be useful before its parent is enumerated.

    This only permits a node to submit evidence. Directory completion still
    requires the listings and reads computed by ``_progress``; a literal path
    inside the declared scope never substitutes for discovering that scope.
    """
    observed = {(tool, path) for tool, path, _ in previous}
    for tool, path, _ in current:
        if (tool, path) in observed:
            continue
        if any(_is_scoped_observation(requirement, tool, path) for requirement in requirements):
            return True
    return False


def node_workspace_observation_feedback(context, store, records) -> str | None:
    """Acquisition nodes must make scoped progress before claiming completion.

    This local check does not demand a whole repository in one Agent call. ACG
    owns decomposition/review; its final gate checks all accepted requirements.
    """
    if getattr(context.step, "capability", None) != "information_extraction":
        return None
    from contracts.workspace_planning import effective_workspace_requirements

    requirements = effective_workspace_requirements(context.run)
    if not requirements:
        return None
    previous = verified_node_workspace_receipts(context.run, store)
    before = _progress(requirements, previous)
    if all(item["complete"] for item in before):
        return None
    current = _verified_receipts(context.run, store, records)
    after = _progress(requirements, (*previous, *current))
    if before != after or _has_new_scoped_observation(requirements, previous, current):
        return None
    return ("Workspace observation requirements remain unmet. Read the authorized relative files or list "
            "the required directories using fs.read/fs.list before completing this acquisition node. "
            "A claim, an unrelated read, a failed read or a partial body is not evidence. "
            "Make scoped progress; ACG can schedule supplemental reading and review. Required gaps: "
            + json.dumps(before, ensure_ascii=False, separators=(",", ":")))


def node_workspace_page_progress(context, store, records, *, role="workspace_acquisition") -> dict | None:
    """Describe a frozen evidence page from correlated receipts, not claims.

    This is advisory feedback for the current conversation. Only the existing
    node settlement and ACG coverage checks can accept the resulting evidence.
    """
    from contracts.planning import TaskImplementationBinding, TaskPlan
    from contracts.workspace_planning import effective_workspace_requirements

    capability = {"workspace_acquisition": "information_extraction", "workspace_review": "verification"}.get(role)
    if capability is None or getattr(context.step, "capability", None) != capability or not store:
        return None
    state = context.run.execution_state
    try:
        plan = TaskPlan.model_validate(state.get("taskPlan"))
        keys = {binding.plan_node_key for raw in state.get("taskBindings", ())
                if (binding := TaskImplementationBinding.model_validate(raw)).acg_node_id == context.step.step_id}
        if len(keys) != 1:
            return None
        nodes = [node for node in plan.nodes if node.key in keys and (
            node.logical_role == role or (
                node.metadata.get("source") == "workspace_review"
                and node.metadata.get("taskType") == role))]
        if len(nodes) != 1:
            return None
        scopes = [constraint["workspaceReview"] for constraint in nodes[0].constraints
                  if isinstance(constraint.get("workspaceReview"), dict)]
        if len(scopes) != 1:
            return None
        targets = tuple(dict.fromkeys(TypeAdapter(tuple[WorkspaceAcquisitionTarget, ...]).validate_python(
            scopes[0].get("targets"))))
        requirements = effective_workspace_requirements(context.run)
        if not targets or not requirements:
            return None
    except (AttributeError, KeyError, TypeError, ValueError):
        # Older/unrelated plans have no formal acquisition page to describe.
        # They continue through the existing completion and coverage checks.
        return None
    receipts = _verified_receipts(context.run, store, [*_current_records(context.run, store), *records])
    observed = {(tool, path) for tool, path, _ in receipts}
    verified = [target.model_dump() for target in targets if ("fs." + target.operation, target.path) in observed]
    remaining = [target.model_dump() for target in targets if ("fs." + target.operation, target.path) not in observed]
    return {"batchComplete": not remaining, "verifiedTargets": verified, "remainingTargets": remaining,
        "verifiedReadCount": len({path for tool, path in observed if tool == "fs.read"}),
        "verifiedListingCount": len({path for tool, path in observed if tool == "fs.list"}),
        "remainingScope": list(_progress(requirements, receipts)),
        "evidenceStatus": "receipt_verified_not_committed"}


def node_workspace_acquisition_progress(context, store, records) -> dict | None:
    """Keep acquisition-turn feedback separate from the review of that page."""
    return node_workspace_page_progress(context, store, records)
