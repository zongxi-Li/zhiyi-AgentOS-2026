package com.kinlin.ai.dto.agentos;

import java.time.Instant;

public record AgentOsReviewResponse(
        String runId,
        String missionId,
        String workflowId,
        AgentOsRunStatus status,
        AgentOsLifecyclePhase lifecyclePhase,
        String lifecycleMessage,
        String currentStepId,
        long runtimeRevision,
        String parentRunId,
        String sourceRunId,
        String supersedesRunId,
        String supersededByRunId,
        String reviewState,
        AgentOsErrorDetail error,
        Instant createdAt,
        Instant updatedAt,
        Instant startedAt,
        String operationId,
        String decision
) implements AgentOsApiResponse {
}
