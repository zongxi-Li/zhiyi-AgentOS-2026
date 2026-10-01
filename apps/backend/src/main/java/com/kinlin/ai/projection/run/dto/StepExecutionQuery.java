package com.kinlin.ai.projection.run.dto;

import java.util.List;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/** Explicit observation fields; never an executable runtime snapshot. */
public record StepExecutionQuery(
        String stepExecutionId,
        String runId,
        String taskId,
        String attemptId,
        String status,
        String startedAt,
        String finishedAt
) implements QueryResponse { }
