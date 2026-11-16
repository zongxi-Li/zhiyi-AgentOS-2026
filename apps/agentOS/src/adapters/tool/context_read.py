"""Read-only model tools backed exclusively by the node's CommunicationReader."""
from __future__ import annotations

from contracts.tools import ToolDefinition, ToolResult


class ContextReadTools:
    def __init__(self, context):
        self.reader = getattr(context, "communication_reader", None)

    def list_tools(self):
        if self.reader is None or self.reader.model_budget is None or not self.reader.available_sources:
            return ()
        common = {"producerStepId": {"type": "string", "minLength": 1},
                  "fields": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1}}
        specs = [
            ("context.list_sources", "List authorized upstream sources and fields with estimated sizes; returns no body.", {}, []),
            ("context.read", "Read selected authorized upstream fields. If the read exceeds budget, use context.read_page.", common,
             ["producerStepId", "fields"]),
            ("context.read_page", "Read one authorized page. Follow nextCursor until null for full coverage; a page alone is incomplete evidence.",
             {**common, "cursor": {"type": ["string", "null"]},
              "pageTokens": {"type": "integer", "minimum": 1, "maximum": self.reader.model_budget.max_read_tokens}},
             ["producerStepId", "fields"]),
        ]
        return tuple(ToolDefinition(name=name, source="communication", description=description,
            parameters={"type": "object", "properties": properties, "required": required, "additionalProperties": False})
            for name, description, properties, required in specs)

    async def execute(self, name, arguments, *, operation_key):
        if name not in {tool.name for tool in self.list_tools()}:
            raise PermissionError("context tool is not enabled")
        if name == "context.list_sources":
            output = {"sources": self.reader.describe_sources(),
                      "budget": self.reader.model_budget.model_dump(by_alias=True)}
        else:
            cursor = None
            if name == "context.read":
                pack = await self.reader.read(arguments["producerStepId"], arguments["fields"], operation_id=operation_key)
            else:
                pack, cursor = await self.reader.read_page(arguments["producerStepId"], arguments["fields"],
                    cursor=arguments.get("cursor"), page_tokens=arguments.get("pageTokens", self.reader.model_budget.page_tokens),
                    operation_id=operation_key)
            output = {"producerStepId": arguments["producerStepId"], "data": pack.data,
                      "evidenceRefs": pack.evidence_refs, "estimatedTokens": pack.tokens_delivered,
                      "scope": "page" if name == "context.read_page" else "fields",
                      "complete": cursor is None and not arguments.get("cursor"),
                      "hasMore": cursor is not None, "nextCursor": cursor}
        return ToolResult(name=name, source="communication", status="succeeded", output=output)
