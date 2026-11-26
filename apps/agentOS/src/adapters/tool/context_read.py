"""Read-only model tools backed exclusively by the node's CommunicationReader."""
from __future__ import annotations

from contracts.tools import ToolDefinition, ToolResult
from contracts.context_read import context_read_parameters, validate_context_read_arguments
from contracts.request_budget import SupplementalReadBudget
from components.communicator.broker import CommunicationAccessError
from components.communicator.contracts import estimate_tokens
from adapters.tool.hands_http import receipt_checksum


class ContextReadTools:
    def __init__(self, context):
        self.context = context
        self.reader = getattr(context, "communication_reader", None)
        step = getattr(context, "step", None)
        self.nested_read_version = (getattr(step, "input", {}).get("contextPolicy") or {}).get("nestedReadVersion")
        self.evidence_enabled = False
        self._evidence = {}

    @property
    def budget(self):
        return self.reader.model_budget or SupplementalReadBudget()

    def admit_evidence(self, record):
        """Register only receipts supplied by the trusted execution or recovery path."""
        reference = record.get("receiptRef")
        if not self.evidence_enabled or record.get("status") != "completed" or not reference:
            return None
        if reference in self._evidence:
            return self._evidence[reference]
        tool = record.get("tool")
        if tool not in {"fs.read", "fs.list"}:
            return None
        run_id, step_id = self.context.run.run_id, record["stepId"]
        store = self.reader.operation_store
        store.assert_reference(kind="output", run_id=run_id, step_id=step_id, reference=reference)
        receipt = store.get_output(run_id=run_id, output_ref=reference)
        identity = receipt.get("identity") or {}
        checksum = record.get("receiptChecksum")
        if (not checksum or receipt.get("checksum") != checksum or receipt_checksum(receipt) != checksum
                or receipt.get("status") != "completed" or receipt.get("capabilityId") != tool
                or identity.get("runId") != run_id or identity.get("stepId") != step_id
                or any(identity.get(key) != record.get(key) for key in ("attemptId", "commitId"))):
            raise CommunicationAccessError("EVIDENCE_DENIED", "receipt does not match admitted evidence")
        output = receipt.get("output") or {}
        field = "entries" if tool == "fs.list" else "content"
        actual_field = "text" if field == "content" and "text" in output else field
        value = output.get(actual_field)
        if field == "entries" and not isinstance(value, list) or field == "content" and not isinstance(value, str):
            return None
        source = {"producerStepId": reference, "sourceStepId": step_id, "receiptRef": reference,
                  "tool": tool, "path": output.get("path"),
                  "fields": [{"name": field, "present": True,
                              "estimatedTokens": estimate_tokens({field: value}), "valueType": type(value).__name__}]}
        self._evidence[reference] = source
        self.reader.admit_receipt_reference(reference)
        return source

    def admit_context_pack_evidence(self):
        """Resolve only receipt references already delivered by the node's ContextPack."""
        if not self.evidence_enabled:
            return
        pack = getattr(self.context, "context_pack", None)
        run_id = self.context.run.run_id

        def fact_sources(value):
            if isinstance(value, dict):
                source = value.get("source")
                if isinstance(source, str) and source.startswith("tool:"):
                    yield source
                for child in value.values():
                    yield from fact_sources(child)
            elif isinstance(value, list):
                for child in value:
                    yield from fact_sources(child)

        references = {reference: set() for reference in getattr(pack, "evidence_refs", ())}
        for producer, data in getattr(pack, "source_data", {}).items():
            for reference in fact_sources(data):
                if reference not in references or references[reference]:
                    references.setdefault(reference, set()).add(producer)
        committed = self.reader.committed_receipt_refs({owner for owners in references.values() for owner in owners})
        for reference, owners in references.items():
            if not reference.startswith("tool:") or reference in self._evidence:
                continue
            if owners and not any((owner, reference) in committed for owner in owners):
                continue
            try:
                receipt = self.reader.operation_store.get_output(run_id=run_id, output_ref=reference)
            except (KeyError, ValueError, PermissionError):
                continue
            identity = receipt.get("identity") or {}
            if (not identity.get("stepId") or identity.get("runId") != run_id
                    or owners and identity["stepId"] not in owners):
                continue
            self.admit_evidence({**identity, "receiptRef": reference, "receiptChecksum": receipt.get("checksum"),
                                 "status": receipt.get("status"), "tool": receipt.get("capabilityId")})

    def _read_evidence(self, reference, arguments, operation_key):
        source = self._evidence[reference]
        field = source["fields"][0]["name"]
        if arguments["fields"] != [field] or arguments.get("path"):
            raise CommunicationAccessError("FIELD_DENIED", "select the evidence field listed by context.list_sources")
        if arguments.get("describe"):
            return {**source, "scope": "structure", "complete": False}
        receipt = self.reader.operation_store.get_output(run_id=self.context.run.run_id, output_ref=reference)
        output = receipt["output"]
        value = output.get("text", output.get("content")) if field == "content" else [
            {key: entry[key] for key in ("name", "type", "size") if key in entry} for entry in output["entries"]
        ]
        cursor = arguments.get("cursor")
        pack, following = self.reader.read_evidence_page(
            reference=reference, producer_step_id=source["sourceStepId"], field=field, value=value,
            cursor=cursor, page_tokens=arguments.get("pageTokens", self.budget.page_tokens),
            operation_id=operation_key,
        )
        return {"producerStepId": reference, "receiptRef": reference, "data": pack.data,
                "evidenceRefs": pack.evidence_refs, "estimatedTokens": pack.tokens_delivered,
                "scope": "evidence_page", "complete": following is None and cursor is None,
                "hasMore": following is not None, "nextCursor": following}

    def list_tools(self):
        upstream = self.reader is not None and self.reader.model_budget is not None and self.reader.available_sources
        if not upstream and not self.evidence_enabled:
            return ()
        nested = type(self.nested_read_version) is int and self.nested_read_version == 1
        page_description = "Read one authorized page. Follow nextCursor until null for full coverage; a page alone is incomplete evidence."
        if nested:
            page_description += (" Select one top-level field and use describe:true to inspect child keys, array indices and sizes "
                "without reading their values. path selects object keys or array indices inside that field; "
                "use it to page a large nested value. A subtree page does not complete the original field.")
        specs = [
            ("context.list_sources", "List authorized upstream sources and fields with estimated sizes; returns no body."),
            ("context.read", "Read selected authorized upstream fields. If the read exceeds budget, use context.read_page."),
            ("context.read_page", page_description),
        ]
        if self.evidence_enabled:
            specs[0] = ("context.list_sources", "List authorized upstream fields and admitted workspace receipts without their bodies.")
            specs[-1] = ("context.read_page", page_description + " For a workspace receipt, use its producerStepId and listed field.")
            if not upstream:
                del specs[1]
        return tuple(ToolDefinition(name=name, source="communication", description=description,
            parameters=context_read_parameters(name, nested_read_version=self.nested_read_version,
                max_read_tokens=self.budget.max_read_tokens))
            for name, description in specs)

    async def execute(self, name, arguments, *, operation_key):
        if name not in {tool.name for tool in self.list_tools()}:
            raise PermissionError("context tool is not enabled")
        validate_context_read_arguments(name, arguments, nested_read_version=self.nested_read_version,
            max_read_tokens=self.budget.max_read_tokens)
        if name == "context.list_sources":
            sources = self.reader.describe_sources() if self.reader.model_budget is not None else []
            output = {"sources": [*sources, *self._evidence.values()],
                      "budget": self.budget.model_dump(by_alias=True)}
        elif arguments["producerStepId"] in self._evidence:
            if name != "context.read_page":
                raise CommunicationAccessError("FIELD_DENIED", "workspace receipts require context.read_page")
            output = self._read_evidence(arguments["producerStepId"], arguments, operation_key)
        elif self.reader.model_budget is None:
            raise CommunicationAccessError("TOPOLOGY_DENIED", "this evidence source is not available")
        elif name == "context.read_page" and arguments.get("describe"):
            output = {"producerStepId": arguments["producerStepId"], "scope": "structure", "complete": False,
                "structure": self.reader.describe_path(arguments["producerStepId"], arguments["fields"],
                    value_path=arguments.get("path", ())), "path": arguments.get("path", [])}
        else:
            cursor = None
            if name == "context.read":
                pack = await self.reader.read(arguments["producerStepId"], arguments["fields"], operation_id=operation_key)
            else:
                path = arguments.get("path", ())
                pack, cursor = await self.reader.read_page(arguments["producerStepId"], arguments["fields"],
                    cursor=arguments.get("cursor"), page_tokens=arguments.get("pageTokens", self.reader.model_budget.page_tokens),
                    operation_id=operation_key, value_path=path)
            output = {"producerStepId": arguments["producerStepId"], "data": pack.data,
                      "evidenceRefs": pack.evidence_refs, "estimatedTokens": pack.tokens_delivered,
                      "scope": "page" if name == "context.read_page" else "fields",
                      "complete": cursor is None and not arguments.get("cursor"),
                      "hasMore": cursor is not None, "nextCursor": cursor}
            if pack.value_path:
                output.update(path=list(pack.value_path), scope="subtree_page", complete=False,
                    subtreeComplete=cursor is None and not arguments.get("cursor"))
        return ToolResult(name=name, source="communication", status="succeeded", output=output)
