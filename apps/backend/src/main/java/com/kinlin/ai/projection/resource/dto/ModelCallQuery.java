package com.kinlin.ai.projection.resource.dto;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * One public model-call ledger row (call identity, model/provider, timing, typed usage,
 * finish reason and the consumed output-policy/quota/pressure fields).
 *
 * <p>Nullable components are the "not observed" states of the upstream audit payloads
 * (error-path audits omit partIndex/callChainId/finishReason; legacy rows may lack
 * provider/model, which the inspector renders as 未知模型). All verified readers guard
 * with {@code ?.}/{@code ||}, so absent equals the previous null.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ModelCallQuery(
        String callId,
        String stepId,
        String provider,
        String model,
        String createdAt,
        long latencyMs,
        TokenUsageQuery usage,
        String finishReason,
        String outputPolicy,
        Long requestedOutputTokens,
        Long effectiveOutputTokens,
        String effectiveReason,
        boolean outputExhausted,
        Integer partIndex,
        String callChainId,
        Double contextPressure
) {
}
