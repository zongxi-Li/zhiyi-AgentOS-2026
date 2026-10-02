package com.kinlin.ai.projection.recovery.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

import java.util.List;

/**
 * Typed run checkpoints response over the agentos_v2.py {@code get_checkpoints}
 * wire: the public recovery-availability facts only. The upstream endpoint never
 * returns checkpoint snapshot data, and this projection keeps it that way — a
 * missing checkpoint yields an empty items list, not a fabricated row.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record CheckpointsQuery(
        String runId,
        List<CheckpointItemQuery> items,
        Long total
) implements QueryResponse {
}
