package com.kinlin.ai.dto.agentos;

import java.time.Instant;
import java.util.Objects;

/** Stable Run list projection; query wiring is deferred to N1.2. */
public record AgentOsRunSummary(
        String runId,
        String missionId,
        String workflowId,
        AgentOsRunStatus status,
        AgentOsLifecyclePhase lifecyclePhase,
        String currentStepId,
        Instant createdAt,
        Instant updatedAt
) {
    public AgentOsRunSummary {
        Objects.requireNonNull(runId, "runId");
        Objects.requireNonNull(missionId, "missionId");
        Objects.requireNonNull(workflowId, "workflowId");
        Objects.requireNonNull(status, "status");
        Objects.requireNonNull(createdAt, "createdAt");
        Objects.requireNonNull(updatedAt, "updatedAt");
    }
}
