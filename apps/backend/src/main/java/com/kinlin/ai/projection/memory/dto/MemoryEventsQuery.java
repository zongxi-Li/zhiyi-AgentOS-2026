package com.kinlin.ai.projection.memory.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

import java.util.List;

/**
 * Typed run memory-events response over the agentos_v2.py {@code get_memory_events}
 * wire: the polling-friendly projection of memory access rows, structured memory
 * events and phase capsules. Field set follows the verified MemoryView/memoryFlow
 * readers; upstream fields without any consumer (budget, eventId, runId, commitId,
 * decision, relations, capsuleRef, evidenceRefs) are dropped and registered in the
 * migration record.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record MemoryEventsQuery(
        String runId,
        List<MemoryEventItemQuery> items,
        Long total
) implements QueryResponse {
}
