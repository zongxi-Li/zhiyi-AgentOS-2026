package com.kinlin.ai.projection.trace.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

import java.util.List;

/**
 * Whitelisted public payload fields of one trace event.
 *
 * <p>Typed keys exist only where a verified frontend reader consumes them
 * (observation.ts / runtimePresentation.ts / RuntimeAuditTimeline.vue); they are
 * populated only when the event family whitelist approves the key, so unknown or
 * historical event types carry an empty payload. Every value comes straight from
 * the upstream wire — no recomputation, no raw-object fallback for mistyped keys.
 *
 * <p>{@code details} carries the bounded public display projection rendered by the
 * generic event detail branch. It never contains unknown keys, internal policy
 * (promptAudit/profile/selectedBindings/pendingMemory), internal references
 * (commitId/checkpointId/patchId/patchRef/graphId) or runtime binding state, and
 * {@code [redacted]}/{@code [truncated]} upstream markers surface as explicit
 * unavailable states instead of invented values.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record TracePayloadQuery(
        String status,
        String tool,
        String name,
        String model,
        String provider,
        String finishReason,
        Long latencyMs,
        String producerStepId,
        List<String> producerStepIds,
        String consumerStepId,
        String interactionId,
        String outputRef,
        String channel,
        List<String> fields,
        List<String> consumedFields,
        List<TraceProducerFieldsQuery> producerFields,
        Long tokens,
        Long tokensDelivered,
        String contractStatus,
        String errorCode,
        String code,
        String message,
        String summary,
        String reason,
        Long graphVersion,
        String attemptId,
        Boolean planningProgress,
        String category,
        String stage,
        String kind,
        Integer attempt,
        Integer retryCount,
        Integer taskCount,
        Integer dependencyCount,
        Integer nodeCount,
        Integer edgeCount,
        Integer constraintCount,
        Integer requiredCapabilityCount,
        Integer expectedArtifactCount,
        Integer timeoutSeconds,
        List<TraceFailedResourceQuery> failedResources,
        List<String> retryStepIds,
        List<TracePublicDetailQuery> details
) implements QueryResponse {
}
