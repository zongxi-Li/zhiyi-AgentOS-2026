package com.kinlin.ai.dto.agentos;

import java.time.Instant;
import java.util.Objects;

public record AgentOsRunResponse(
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
        Instant startedAt
) implements AgentOsApiResponse {
    public AgentOsRunResponse {
        Objects.requireNonNull(runId, "runId");
        Objects.requireNonNull(missionId, "missionId");
        Objects.requireNonNull(workflowId, "workflowId");
        Objects.requireNonNull(status, "status");
        Objects.requireNonNull(createdAt, "createdAt");
        Objects.requireNonNull(updatedAt, "updatedAt");
    }
}
