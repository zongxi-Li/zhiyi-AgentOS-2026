package com.kinlin.ai.dto.agentos;

import java.time.Instant;
import java.util.Objects;

/** Stable Mission list projection; query wiring is deferred to N1.2. */
public record AgentOsMissionSummary(
        String missionId,
        String title,
        String status,
        String latestRunId,
        AgentOsRunStatus latestRunStatus,
        int runCount,
        Instant createdAt,
        Instant updatedAt
) {
    public AgentOsMissionSummary {
        Objects.requireNonNull(missionId, "missionId");
        Objects.requireNonNull(title, "title");
        Objects.requireNonNull(status, "status");
        Objects.requireNonNull(createdAt, "createdAt");
        Objects.requireNonNull(updatedAt, "updatedAt");
        if (runCount < 0) {
            throw new IllegalArgumentException("runCount must be non-negative");
        }
    }
}
