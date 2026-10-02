package com.kinlin.ai.projection.resource.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/**
 * Typed Run resource-usage overview over the agentos_v2.py {@code get_resource_usage} wire.
 *
 * <p>The upstream {@code scheduler} object (activeSlots/queueDepth/checkpointCount/recoveryCount)
 * has no frontend consumer (only the acg.ts declaration and a spec fixture) and is dropped
 * here — the four fields become absent. capability subkeys without a reader
 * (maxTokensField/features/maxTokensRequired/observedAt) are likewise omitted. Every nullable
 * component follows the NON_NULL rule; all verified readers guard with {@code ?.}/{@code ||}/
 * {@code ??}/{@code == null}, so absent equals the previous null.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record RunResourceUsageQuery(
        String runId,
        ModelCapabilityQuery capability,
        String capabilitySource,
        String outputPolicy,
        UsageSummaryQuery usage,
        ContextPressureQuery contextPressure,
        CompositionQuery composition
) implements QueryResponse {
}
