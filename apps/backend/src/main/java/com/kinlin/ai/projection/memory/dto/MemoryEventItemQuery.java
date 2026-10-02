package com.kinlin.ai.projection.memory.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

import java.util.List;

/**
 * One memory-events row, the three upstream variants flattened over the row's
 * {@code kind}: {@code memory_access} fills retrievalMode/hitRefs/fallbackReason,
 * {@code memory_event} fills summary/metrics, {@code phase_capsule} fills
 * phaseId/sourceMemoryRefs/tokenCount. Unknown kinds keep only the kind plus the
 * common step/created fields instead of failing the whole polled response.
 *
 * <p>{@code tokenCount} is a String on purpose: the upstream redaction marks it as
 * {@code [redacted]} for every capsule, so the honest wire type is text and no
 * number may be invented.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record MemoryEventItemQuery(
        String kind,
        String stepId,
        String createdAt,
        String retrievalMode,
        List<String> hitRefs,
        String fallbackReason,
        String summary,
        MemoryEventMetricsQuery metrics,
        String phaseId,
        List<String> sourceMemoryRefs,
        String tokenCount
) implements QueryResponse {
}
