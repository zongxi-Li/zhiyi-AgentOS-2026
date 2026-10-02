package com.kinlin.ai.projection.output.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/**
 * Typed GET /runs/{runId}/outputs/{outputRef} response over the agentos_v2.py
 * {@code get_output} wire. {@code content} is the user product body and uses the
 * dedicated content value grammar — the only DTO family allowed to carry it
 * (guard-verified); it must never be reused for trace/memory/provenance/health or
 * any control metadata.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record OutputQuery(
        String runId,
        String outputRef,
        ContentValueQuery content
) implements QueryResponse {
}
