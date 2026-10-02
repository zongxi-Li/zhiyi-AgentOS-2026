package com.kinlin.ai.projection.trace.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/**
 * One public trace event: the upstream {@code TraceEvent} skeleton plus the
 * whitelisted public payload projection.
 *
 * <p>Unknown or historical {@code eventType} values never fail the trace — they
 * keep this public skeleton with an empty payload projection. Structural damage
 * to the skeleton (missing eventId/eventType/createdAt/durationMs/payload object)
 * is a contract break and fails loudly upstream of this DTO.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record TraceEventQuery(
        String eventId,
        String runId,
        String stepId,
        String agentName,
        String eventType,
        String observation,
        Long durationMs,
        String createdAt,
        TracePayloadQuery payload
) implements QueryResponse {
}
