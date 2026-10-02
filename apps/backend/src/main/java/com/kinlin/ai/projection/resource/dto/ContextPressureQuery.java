package com.kinlin.ai.projection.resource.dto;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * Public context-pressure projection: finite ratios only, token counters exact.
 *
 * <p>Null pressure/token values are the "not observed" state (readers guard with
 * {@code == null}); {@code source} is always one of usage_derived/capability_declared/unknown.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ContextPressureQuery(
        Double current,
        Double peak,
        Long currentInputTokens,
        Long peakInputTokens,
        Long contextWindowTokens,
        String source
) {
}
