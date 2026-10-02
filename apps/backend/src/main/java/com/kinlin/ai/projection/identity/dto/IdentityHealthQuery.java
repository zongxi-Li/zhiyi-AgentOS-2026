package com.kinlin.ai.projection.identity.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/**
 * Typed public identity projection health over the agentos_v2.py
 * {@code get_identity_health} wire: backlog/failure counters, the oldest pending
 * event and the startup reconciliation summary. No repository, migration or runtime
 * internals ride along — the upstream endpoint already returns exactly this summary.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record IdentityHealthQuery(
        String status,
        String source,
        Long backlogCount,
        Long failedCount,
        String oldestEventAt,
        Long unappliedEventCount,
        Long inboxBacklog,
        Long outboxBacklog,
        StartupReconciliationQuery startupReconciliation
) implements QueryResponse {

    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record StartupReconciliationQuery(
            Long examinedMissions,
            Long examinedRuns,
            Long repairedMissions,
            Long repairedRuns,
            Long replayedEvents,
            Long failureCount
    ) implements QueryResponse {
    }
}
