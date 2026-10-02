package com.kinlin.ai.projection.resource.dto;

import java.util.List;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/**
 * Typed model-call page over the agentos_v2.py {@code get_resource_usage_calls} wire.
 *
 * <p>Filtering, cursor paging and totals stay upstream-owned: {@code nextCursor} passes
 * through verbatim (never parsed or rewritten), {@code items} must be present — a missing
 * list fails the contract instead of passing as an empty page. Each row drops the upstream
 * {@code capability} dict (declared nowhere in the frontend contract and read by no consumer).
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ResourceCallPageQuery(
        String runId,
        List<ModelCallQuery> items,
        String nextCursor,
        int total
) implements QueryResponse {
    public ResourceCallPageQuery {
        items = List.copyOf(items);
    }
}
