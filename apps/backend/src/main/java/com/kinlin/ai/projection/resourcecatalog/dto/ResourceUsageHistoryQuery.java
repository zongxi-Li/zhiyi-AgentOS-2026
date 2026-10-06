package com.kinlin.ai.projection.resourcecatalog.dto;

import java.util.List;

import com.kinlin.ai.projection.common.dto.QueryResponse;

/** Typed recent-attempt usage history of one catalog resource (identity facts only). */
public record ResourceUsageHistoryQuery(
        String resourceId,
        List<Item> items,
        Long total
) implements QueryResponse {

    public ResourceUsageHistoryQuery {
        items = List.copyOf(items);
    }

    /** One attempt binding row as persisted by the identity graph. */
    public record Item(
            String bindingId,
            String attemptId,
            String runId,
            String taskId,
            String missionId,
            String taskTitle,
            String semanticTaskKey,
            String acgNodeId,
            String agentId,
            String modelId,
            Long attemptNumber,
            String attemptStatus,
            String startedAt,
            String finishedAt,
            String boundAt
    ) { }
}
