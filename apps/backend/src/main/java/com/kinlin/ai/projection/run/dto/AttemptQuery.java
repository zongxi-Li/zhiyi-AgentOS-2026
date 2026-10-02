package com.kinlin.ai.projection.run.dto;

import java.util.List;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/** Explicit observation fields; never an executable runtime snapshot. */
public record AttemptQuery(
        String attemptId,
        String runId,
        String taskId,
        String status,
        Integer attemptNumber,
        String startedAt,
        String finishedAt,
        String failureReason
) implements QueryResponse { }
