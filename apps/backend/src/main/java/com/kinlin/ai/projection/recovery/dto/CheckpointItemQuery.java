package com.kinlin.ai.projection.recovery.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/**
 * One public checkpoint availability row: the reference the frontend needs to
 * render the recovery entry, the store version, and the real canResume fact
 * (upstream computes it strictly from the waiting_review status).
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record CheckpointItemQuery(
        String checkpointId,
        Long version,
        Boolean canResume
) implements QueryResponse {
}
