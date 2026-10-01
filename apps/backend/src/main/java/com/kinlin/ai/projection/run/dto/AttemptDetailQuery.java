package com.kinlin.ai.projection.run.dto;

import java.util.List;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/** Explicit observation fields; never an executable runtime snapshot. */
public record AttemptDetailQuery(
        AttemptQuery attempt,
        List<StepExecutionQuery> executions,
        ResourceUseQuery resourceUse
) implements QueryResponse {
    public AttemptDetailQuery {
        executions = List.copyOf(executions);
    }
 }
