package com.kinlin.ai.projection.statistics.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

import java.util.List;

/**
 * Typed per-user statistics over the StatisticsService wire. The hour
 * distribution keeps its reader-facing meaning as typed hour/count rows; counts
 * are the service's own aggregates, never recomputed.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record UserStatisticsQuery(
        Long totalConversations,
        Long totalMessages,
        Double avgMessagesPerConversation,
        Long recentMessages,
        List<HourCountQuery> hourDistribution
) implements QueryResponse {

    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record HourCountQuery(
            Integer hour,
            Long count
    ) implements QueryResponse {
    }
}
