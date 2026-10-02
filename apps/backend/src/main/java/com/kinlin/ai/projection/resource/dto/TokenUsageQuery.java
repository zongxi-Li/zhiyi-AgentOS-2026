package com.kinlin.ai.projection.resource.dto;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * Per-call token usage, upstream-normalized to six exact non-negative integers (zero stays
 * zero — the frontend dereferences {@code call.usage.*} unguarded, so this object is required).
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record TokenUsageQuery(
        long inputTokens,
        long outputTokens,
        long cacheReadTokens,
        long cacheWriteTokens,
        long reasoningTokens,
        long totalTokens
) {
}
