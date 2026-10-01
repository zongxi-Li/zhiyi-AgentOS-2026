package com.kinlin.ai.projection.run.dto;

import java.util.List;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/** Explicit observation fields; never an executable runtime snapshot. */
public record StepQuery(
        String stepId,
        String name,
        String agentName,
        String capability,
        String status,
        Integer attempt,
        Integer retryCount,
        Boolean reviewRequired,
        String outputRef,
        String outputSummary,
        String startedAt,
        String completedAt
) implements QueryResponse { }
