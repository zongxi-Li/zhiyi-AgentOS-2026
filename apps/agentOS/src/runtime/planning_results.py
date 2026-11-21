"""Frozen committed-result discovery and paged reads for strategic planning.

The observation supplies the permitted addresses. Existing commit/audit lineage
and CommunicationBroker remain the authorities for provenance and pagination.
Read receipts contain request identities and checksums, never another body copy.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json

from components.communicator.broker import CommunicationBroker
from components.communicator.contracts import estimate_tokens
from components.communicator.manifest import CommunicationManifest, CommunicationRule
from contracts import stable_checksum
from contracts.planning_context import PLANNING_CONTEXT_METADATA_FIELD, PLANNING_CONTEXT_OWNER, planning_context_reference
from contracts.runtime_planning import PlanningResultField, PlanningResultIndexEntry


_UNRESOLVED_FIELDS = frozenset({"open_questions", "openQuestions", "unknowns", "unresolvedGaps",
    "blockers", "risks", "risk_analysis", "assumptions"})
_EVIDENCE_FIELDS = frozenset({"evidence_refs", "evidenceRefs", "sources", "sourceRefs", "source_refs"})


def _encoded_size(value):
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def committed_output_commit(store, run_id, step_id, output_ref, *, commits=None):
    """Shared ownership and unique-commit check for planning source readers."""
    store.assert_reference(kind="output", run_id=run_id, step_id=step_id, reference=output_ref)
    commits = [commit for commit in (store.list_node_commits(run_id=run_id) if commits is None else commits)
        if commit.get("stage") == "committed" and commit.get("outputRef") == output_ref]
    if len(commits) != 1:
        raise ValueError("completed output requires one immutable node commit")
    return commits[0]


def resolve_committed_result(services, run_id, step_id, output_ref, visited=frozenset()):
    """Follow the existing retry lineage to its single immutable audited commit."""
    if run_id in visited:
        raise ValueError("cyclic reused output lineage")
    commit = committed_output_commit(services.execution_value_store, run_id, step_id, output_ref)
    source_id, source_ref = commit.get("reusedFromRunId"), commit.get("reusedFromOutputRef")
    if source_id or source_ref:
        if not source_id or not source_ref:
            raise ValueError("reused output lineage requires both source addresses")
        return resolve_committed_result(services, source_id, step_id, source_ref, visited | {run_id})
    decision_ref = commit.get("auditDecisionRef")
    if not isinstance(decision_ref, str):
        raise ValueError("completed node requires a persisted audit decision")
    decision = services.decision_store.assert_decision(run_id=run_id, step_id=step_id,
        decision_ref=decision_ref, outcomes={"allow", "review"})
    return commit, decision, run_id


def committed_result_index_entry(*, step, task_key, task, output_ref, payload, commit, audit,
                                 source_run_id, review_resolved, artifact_refs=()):
    """Index every declared or actually produced field without guessing a summary."""
    names = sorted(set((step.output_spec or {}).get("properties") or {}) | set(payload))
    fields = tuple(PlanningResultField(name=name, present=name in payload,
        valueType=type(payload[name]).__name__ if name in payload else "missing",
        byteLength=_encoded_size(payload[name]) if name in payload else 0,
        estimatedTokens=estimate_tokens({name: payload[name]}) if name in payload else 0,
        itemCount=len(payload[name]) if name in payload and isinstance(payload[name], (list, dict)) else None,
        purpose="unresolved" if name in _UNRESOLVED_FIELDS else "evidence" if name in _EVIDENCE_FIELDS else "result")
        for name in names)
    # Agent-produced sources may contain arbitrary source bodies. Expose their
    # field addresses/sizes above; only commit-owned receipt addresses belong
    # directly in this reference index.
    references = [call["receiptRef"] for call in commit.get("toolCalls") or ()
        if isinstance(call, dict) and isinstance(call.get("receiptRef"), str)]
    return PlanningResultIndexEntry(stepId=step.step_id, taskKey=task_key,
        title=task.title if task is not None else step.name,
        objective=task.objective if task is not None else step.goal or step.name,
        logicalRole=step.logical_role, outputRef=output_ref, commitId=commit["commitId"],
        auditRef=audit.decision_id, auditOutcome=audit.outcome,
        sourceRunId=source_run_id, sourceOutputRef=commit["outputRef"], outputChecksum=stable_checksum(payload),
        byteLength=_encoded_size(payload), estimatedTokens=estimate_tokens(payload), fields=fields,
        evidenceRefs=tuple(dict.fromkeys(references)),
        unresolvedFields=tuple(field.name for field in fields
            if field.purpose == "unresolved" and field.present and payload[field.name]),
        artifactRefs=tuple(artifact_refs), readable=True,
        unavailableReason=None if review_resolved else "REVIEW_UNRESOLVED")


class PlanningResultReader:
    """One frozen observation's read view; no current result set is rescanned."""

    def __init__(self, *, services, observation):
        self.services = services
        self.observation = observation.model_copy(deep=True)
        self.observation_id = self.observation.fingerprint()
        entries = self.observation.committed_results
        if (len({entry.step_id for entry in entries}) != len(entries)
                or len({entry.output_ref for entry in entries}) != len(entries)):
            raise ValueError("planning result index contains ambiguous addresses")
        self.entries = {entry.step_id: entry for entry in entries}
        self.contexts = {entry.context_ref: entry for entry in self.observation.context_catalog}
        if len(self.contexts) != len(self.observation.context_catalog):
            raise ValueError("planning context catalog contains ambiguous addresses")
        self.broker = CommunicationBroker(value_store=services.execution_value_store,
            manifest=CommunicationManifest(run_id=self.observation.run_id, rules=tuple(
                CommunicationRule(producer_step_id=entry.step_id, consumer_step_id="__planner__",
                    allowed_fields=tuple(field.name for field in entry.fields), channel=f"planning-result:{entry.step_id}")
                for entry in entries)))
        self.context_brokers = {reference: CommunicationBroker(value_store=services.execution_value_store,
            manifest=CommunicationManifest(run_id=self.observation.run_id, rules=(
                CommunicationRule(producer_step_id=PLANNING_CONTEXT_OWNER, consumer_step_id="__planner__",
                    allowed_fields=tuple(field.name for field in entry.fields), channel=f"planning-context:{reference}"),)))
            for reference, entry in self.contexts.items()}

    def _source(self, step_id, output_ref):
        matches = [entry for entry in self.entries.values()
            if (step_id is None or entry.step_id == step_id) and (output_ref is None or entry.output_ref == output_ref)]
        if not (step_id or output_ref) or len(matches) != 1:
            raise ValueError("planning result read must identify one indexed step or output reference")
        entry = matches[0]
        fact = next((step for step in self.observation.steps if step.step_id == entry.step_id), None)
        if (fact is None or fact.status not in {"completed", "waiting_review"} or fact.task_key != entry.task_key
                or (fact.output_ref, fact.commit_id, fact.audit_ref, fact.audit_outcome)
                != (entry.output_ref, entry.commit_id, entry.audit_ref, entry.audit_outcome)):
            raise ValueError("planning result index differs from its frozen committed observation")
        commit, audit, owner = resolve_committed_result(self.services, self.observation.run_id,
            entry.step_id, entry.output_ref)
        if ((commit["commitId"], audit.decision_id, audit.outcome, owner, commit["outputRef"])
                != (entry.commit_id, entry.audit_ref, entry.audit_outcome, entry.source_run_id, entry.source_output_ref)):
            raise ValueError("planning result commit or audit lineage changed")
        store = self.services.execution_value_store
        payload = store.get_output(run_id=self.observation.run_id, output_ref=entry.output_ref)
        original = store.get_output(run_id=owner, output_ref=entry.source_output_ref)
        if (stable_checksum(payload) != entry.output_checksum or stable_checksum(original) != entry.output_checksum
                or set(payload) - {field.name for field in entry.fields}):
            raise ValueError("planning result contents differ from their frozen index")
        return entry

    def _context_source(self, context_ref):
        entry = self.contexts.get(context_ref)
        if entry is None:
            raise ValueError("planning context reference is not in the frozen catalog")
        store = self.services.execution_value_store
        store.assert_reference(kind="output", run_id=self.observation.run_id,
            step_id=PLANNING_CONTEXT_OWNER, reference=context_ref)
        payload = store.get_output(run_id=self.observation.run_id, output_ref=context_ref)
        metadata = payload.get(PLANNING_CONTEXT_METADATA_FIELD) or {}
        if (metadata != {"version": 1, "runId": self.observation.run_id,
                "contextKind": entry.context_kind, "sourceRunId": entry.source_run_id,
                "stepId": entry.step_id, "attemptId": entry.attempt_id, "operationId": entry.operation_id,
                "originalRef": entry.original_ref, "status": entry.status, "trust": entry.trust}
                or context_ref != planning_context_reference(self.observation.run_id, payload)
                or stable_checksum(payload) != entry.checksum
                or {field.name for field in entry.fields} != set(payload) - {PLANNING_CONTEXT_METADATA_FIELD}):
            raise ValueError("planning context snapshot identity or contents changed")
        return entry

    async def read_page(self, *, step_id=None, output_ref=None, context_ref=None, catalog=None, context_kind=None,
                        fields=(), cursor=None,
                        page_tokens=2048, path=(), describe=False, operation_id):
        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("planning result read requires a stable operation_id")
        if not isinstance(fields, (tuple, list)) or any(not isinstance(field, str) for field in fields):
            raise ValueError("planning result fields must be a field-name list")
        if type(describe) is not bool:
            raise ValueError("describe must be a boolean")
        path = CommunicationBroker._normalize_value_path(path)
        if catalog is not None:
            if context_ref is not None or output_ref is not None:
                raise ValueError("catalog cannot be combined with a context or output reference")
            from runtime.planning_catalog_reader import read_planning_catalog_page
            return await read_planning_catalog_page(self, catalog=catalog, step_id=step_id,
                context_kind=context_kind, fields=fields, cursor=cursor, page_tokens=page_tokens,
                path=path, describe=describe, operation_id=operation_id)
        if context_kind is not None:
            raise ValueError("context_kind requires a contexts catalog query")
        if context_ref is not None:
            if step_id is not None or output_ref is not None:
                raise ValueError("context_ref cannot be combined with a result source")
            entry = self._context_source(context_ref)
            reference, checksum, producer = context_ref, entry.checksum, PLANNING_CONTEXT_OWNER
            broker = self.context_brokers[context_ref]
            address = {"contextRef": context_ref}
            receipt_source = {**address, "checksum": checksum}
            result_source = {**receipt_source, "contextKind": entry.context_kind, "status": entry.status,
                "trust": entry.trust, "stepId": entry.step_id}
        else:
            entry = self._source(step_id, output_ref)
            reference, checksum, producer, broker = entry.output_ref, entry.output_checksum, entry.step_id, self.broker
            address = {"stepId": entry.step_id, "outputRef": reference}
            receipt_source = {**address, "commitId": entry.commit_id, "outputChecksum": checksum}
            result_source = {**receipt_source, "status": "review_pending"
                if entry.unavailable_reason == "REVIEW_UNRESOLVED" else "committed",
                "trust": "agent_generated", "auditOutcome": entry.audit_outcome}
        selected = tuple(dict.fromkeys(fields)) or tuple(field.name for field in entry.fields)
        if not selected or set(selected) - {field.name for field in entry.fields}:
            raise ValueError("planning result fields exceed the frozen index")
        if path and len(selected) != 1:
            raise ValueError("a nested path must select one top-level field")
        traversal = {"path": list(path), "describe": describe} if path or describe else {}
        source_identity = stable_checksum([self.observation_id, reference, checksum, selected,
            *([traversal] if traversal else [])])
        if cursor is not None:
            if not isinstance(cursor, str) or not cursor.startswith(source_identity + ":"):
                raise ValueError("planning result cursor belongs to a different observation, source or field selection")
            broker_cursor = cursor[len(source_identity) + 1:]
        else:
            broker_cursor = None
        args_hash = stable_checksum({"observationId": self.observation_id, **address,
            "fields": selected, "cursor": cursor, "pageTokens": page_tokens, **traversal})
        key = f"planning-result-read:{self.observation_id}:{stable_checksum(operation_id)}"
        store = self.services.execution_value_store
        previous = store.get_tool_value(run_id=self.observation.run_id, key=key)
        if previous is not None and previous.get("argsHash") != args_hash:
            raise ValueError("planning result operation_id conflicts with its original request")
        source = dict(run_id=self.observation.run_id, consumer_step_id="__planner__", producer_step_id=producer,
            output_ref=reference, requested_fields=selected)
        if describe:
            if cursor is not None:
                raise ValueError("a structure description does not take a page cursor")
            description = (broker.describe_reference_path(**source, value_path=path) if len(selected) == 1
                else {"scope": "structure", "fields": [field.model_dump(by_alias=True, mode="json")
                    for field in entry.fields if field.name in selected]})
            data, following = {"description": description}, None
            tokens = estimate_tokens(data)
        else:
            pack, following = await broker.read_reference_page(**source, cursor=broker_cursor, page_tokens=page_tokens,
                reason="inspect existing planning context", operation_id=key,
                **({"value_path": path} if path else {}))
            data, tokens = pack.data, pack.tokens_delivered
        next_cursor = source_identity + ":" + following if following is not None else None
        receipt = {"version": 1, "observationId": self.observation_id, "argsHash": args_hash,
            **receipt_source, "dataChecksum": stable_checksum(data), "nextCursor": next_cursor, "tokensDelivered": tokens}
        if previous is not None and previous != receipt:
            raise ValueError("planning result replay differs from its immutable read receipt")
        store.put_tool_value(run_id=self.observation.run_id, step_id="__planner__", key=key, payload=receipt)
        return {"observationId": self.observation_id, "graphVersion": self.observation.graph_version,
            **result_source, "sourceRunId": entry.source_run_id, "fields": list(selected), "data": deepcopy(data),
            "nextCursor": next_cursor, "tokensDelivered": tokens, **traversal,
            **({"scope": "structure" if describe else "subtree_page", "complete": False} if path or describe else {})}


def read_planning_result_page(services, observation, **kwargs):
    """Synchronous planning-worker entry; every call retains the sealed source set."""
    return asyncio.run(PlanningResultReader(services=services, observation=observation).read_page(**kwargs))


__all__ = ["PlanningResultReader", "read_planning_result_page", "resolve_committed_result",
    "committed_result_index_entry", "committed_output_commit"]
