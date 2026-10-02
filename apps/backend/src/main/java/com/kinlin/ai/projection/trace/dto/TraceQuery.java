package com.kinlin.ai.projection.trace.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

import java.util.List;

/**
 * Typed run trace envelope over the agentos_v2.py {@code get_trace} wire.
 *
 * <p>{@code eventCount} keeps the upstream semantics exactly: it counts the full
 * persisted run trace, while the {@code events} list stays the upstream-ordered,
 * upstream-filtered projection (the workspace view removes delta/activity rows
 * without touching the count, so {@code eventCount > events.size()} is valid).
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record TraceQuery(
        String runId,
        String missionId,
        String workflowId,
        String domain,
        String status,
        Long eventCount,
        List<TraceEventQuery> events
) implements QueryResponse {
}
