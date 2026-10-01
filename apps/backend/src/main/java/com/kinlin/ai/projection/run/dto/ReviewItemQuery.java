package com.kinlin.ai.projection.run.dto;

import java.util.List;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/** Explicit observation fields; never an executable runtime snapshot. */
public record ReviewItemQuery(
        String reviewId,
        String runId,
        String stepId,
        String decision,
        String reviewer,
        String comment,
        String createdAt
) implements QueryResponse { }
