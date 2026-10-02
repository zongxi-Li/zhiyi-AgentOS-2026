package com.kinlin.ai.projection.trace.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/**
 * One bounded public display row of a trace event payload: the whitelisted key,
 * its display text as formatted by the server-side projector, and the value kind
 * the frontend needs to keep its current code/not-code rendering.
 *
 * <p>{@code kind} is a closed vocabulary: string, number, boolean, list, object,
 * redacted (upstream {@code [redacted]} marker) and truncated (upstream
 * {@code [truncated]} depth marker). Null values produce no row at all.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record TracePublicDetailQuery(
        String key,
        String value,
        String kind
) implements QueryResponse {
}
