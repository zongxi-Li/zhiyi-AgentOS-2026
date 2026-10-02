package com.kinlin.ai.projection.memory.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/**
 * The four structured memory-event counters the frontend formatter renders
 * (memoryFlow formatMetrics); other upstream metric keys have no reader and are
 * dropped.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record MemoryEventMetricsQuery(
        Long fieldCount,
        Long evidenceCount,
        Long modelInvocationCount,
        Long toolCallCount
) implements QueryResponse {
}
