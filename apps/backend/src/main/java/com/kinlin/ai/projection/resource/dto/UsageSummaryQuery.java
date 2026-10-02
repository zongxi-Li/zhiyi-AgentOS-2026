package com.kinlin.ai.projection.resource.dto;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * Upstream-computed usage totals; always present (zero counts stay zero, never faked).
 *
 * <p>Token sums and latency keep the exact upstream integers (long — a long-lived run can
 * exceed the int range); {@code cacheHitRatio} is the upstream finite ratio or absent when
 * uncomputable (zero input tokens). All primitive fields always serialize.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record UsageSummaryQuery(
        long inputTokens,
        long outputTokens,
        long cacheReadTokens,
        long cacheWriteTokens,
        long reasoningTokens,
        long totalTokens,
        int callCount,
        int retryCount,
        long latencyMs,
        Double cacheHitRatio
) {
}
