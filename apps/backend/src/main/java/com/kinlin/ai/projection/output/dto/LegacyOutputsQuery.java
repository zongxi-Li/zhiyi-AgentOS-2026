package com.kinlin.ai.projection.output.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

import java.util.List;

/**
 * Typed GET /runs/{runId}/legacy-outputs response over the agentos_v2.py
 * {@code get_legacy_outputs} wire (the pre-identity compatibility endpoint). The
 * user product bodies use the same content value grammar as the active outputs
 * endpoint.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record LegacyOutputsQuery(
        String runId,
        List<LegacyOutputItemQuery> items
) implements QueryResponse {
}
