"""Read-only model tools backed exclusively by the node's CommunicationReader."""
from __future__ import annotations

from contracts.tools import ToolDefinition, ToolResult
from contracts.context_read import context_read_parameters, validate_context_read_arguments


class ContextReadTools:
    def __init__(self, context):
        self.reader = getattr(context, "communication_reader", None)
        step = getattr(context, "step", None)
        self.nested_read_version = (getattr(step, "input", {}).get("contextPolicy") or {}).get("nestedReadVersion")

    def list_tools(self):
        if self.reader is None or self.reader.model_budget is None or not self.reader.available_sources:
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
        return tuple(ToolDefinition(name=name, source="communication", description=description,
            parameters=context_read_parameters(name, nested_read_version=self.nested_read_version,
                max_read_tokens=self.reader.model_budget.max_read_tokens))
            for name, description in specs)

    async def execute(self, name, arguments, *, operation_key):
        if name not in {tool.name for tool in self.list_tools()}:
            raise PermissionError("context tool is not enabled")
        validate_context_read_arguments(name, arguments, nested_read_version=self.nested_read_version,
            max_read_tokens=self.reader.model_budget.max_read_tokens)
        if name == "context.list_sources":
            output = {"sources": self.reader.describe_sources(),
                      "budget": self.reader.model_budget.model_dump(by_alias=True)}
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
