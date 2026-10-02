package com.kinlin.ai.projection.trace.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/**
 * One failed resource of a {@code run_recovered} failover event, exactly as the
 * runtime produces it: the step that failed, the resource that failed it, and the
 * bounded upstream error text (str(error)[:500]).
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record TraceFailedResourceQuery(
        String stepId,
        String resourceId,
        String error
) implements QueryResponse {
}
