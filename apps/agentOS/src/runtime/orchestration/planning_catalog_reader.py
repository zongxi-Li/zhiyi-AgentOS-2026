"""Page an observation's exact context/result directory through the same Broker."""
from __future__ import annotations

from components.communicator.broker import CommunicationBroker
from components.communicator.contracts import estimate_tokens
from components.communicator.manifest import CommunicationManifest, CommunicationRule
from components.executor.value_store import InMemoryExecutionValueStore
from contracts import stable_checksum


async def read_planning_catalog_page(reader, *, catalog, step_id, context_kind, fields, cursor,
                                     page_tokens, path, describe, operation_id):
    if catalog not in {"contexts", "results"}:
        raise ValueError("unknown planning catalog")
    if context_kind is not None and catalog != "contexts":
        raise ValueError("context_kind filters only the contexts catalog")
    if fields and tuple(fields) != ("entries",):
        raise ValueError("catalog pages expose the entries field")
    if type(page_tokens) is not int or page_tokens < 1:
        raise ValueError("page_tokens must be a positive integer")
    observation, store = reader.observation, reader.services.execution_value_store
    entries = observation.context_catalog if catalog == "contexts" else observation.committed_results
    selected = [entry.model_dump(by_alias=True, mode="json") for entry in entries
        if (step_id is None or entry.step_id == step_id)
        and (context_kind is None or entry.context_kind == context_kind)]
    filters = {"stepId": step_id, "contextKind": context_kind}
    body = {"entries": selected}
    digest = stable_checksum(body)
    source_identity = stable_checksum([reader.observation_id, catalog, filters, digest, list(path), describe])
    if cursor is not None:
        if not isinstance(cursor, str) or not cursor.startswith(source_identity + ":"):
            raise ValueError("planning catalog cursor belongs to another observation or filter")
        broker_cursor = cursor[len(source_identity) + 1:]
    else:
        broker_cursor = None
    args_hash = stable_checksum({"observationId": reader.observation_id, "catalog": catalog,
        **filters, "cursor": cursor, "pageTokens": page_tokens, "path": list(path), "describe": describe})
    key = f"planning-result-read:{reader.observation_id}:{stable_checksum(operation_id)}"
    previous = store.get_tool_value(run_id=observation.run_id, key=key)
    if previous is not None and previous.get("argsHash") != args_hash:
        raise ValueError("planning result operation_id conflicts with its original request")
    # Reuse the Broker's exact cursor, path and budget checks before sealing
    # anything. Invalid model queries must not create durable catalog values.
    staging = InMemoryExecutionValueStore()
    catalog_key = "planning-catalog:" + stable_checksum([reader.observation_id, catalog, filters, digest])
    reference = staging.put_tool_value(run_id=observation.run_id, step_id="__planner_catalog__",
        key=catalog_key, payload=body)
    broker = CommunicationBroker(value_store=staging, manifest=CommunicationManifest(run_id=observation.run_id,
        rules=(CommunicationRule(producer_step_id="__planner_catalog__", consumer_step_id="__planner__",
            allowed_fields=("entries",), channel=f"planning-catalog:{catalog}"),)))
    source = dict(run_id=observation.run_id, consumer_step_id="__planner__", producer_step_id="__planner_catalog__",
        output_ref=reference, requested_fields=("entries",))
    if describe:
        if cursor is not None:
            raise ValueError("a structure description does not take a page cursor")
        data = {"description": broker.describe_reference_path(**source, value_path=path)}
        following, tokens = None, estimate_tokens(data)
    else:
        pack, following = await broker.read_reference_page(**source, cursor=broker_cursor, page_tokens=page_tokens,
            reason="inspect complete frozen planning directory", operation_id=key,
            **({"value_path": path} if path else {}))
        data, tokens = pack.data, pack.tokens_delivered
    next_cursor = source_identity + ":" + following if following is not None else None
    receipt = {"version": 1, "observationId": reader.observation_id, "argsHash": args_hash,
        "catalog": catalog, "catalogRef": reference, "checksum": digest, "dataChecksum": stable_checksum(data),
        "nextCursor": next_cursor, "tokensDelivered": tokens}
    if previous is not None and previous != receipt:
        raise ValueError("planning catalog replay differs from its immutable read receipt")
    store.put_tool_value(run_id=observation.run_id, step_id="__planner_catalog__", key=catalog_key, payload=body)
    store.put_tool_value(run_id=observation.run_id, step_id="__planner__", key=key, payload=receipt)
    return {"observationId": reader.observation_id, "graphVersion": observation.graph_version,
        "catalog": catalog, "count": len(selected), "filters": filters, "fields": ["entries"],
        "data": data, "nextCursor": next_cursor, "tokensDelivered": tokens,
        **({"path": list(path), "describe": describe, "scope": "structure" if describe else "subtree_page",
            "complete": False} if path or describe else {})}
