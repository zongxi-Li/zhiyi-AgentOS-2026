package com.kinlin.ai.projection.statistics.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/** Typed system-wide statistics over the StatisticsService wire. */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record SystemStatisticsQuery(
        Long totalConversations,
        Long totalMessages,
        Long activeUsers,
        Double avgMessagesPerConversation
) implements QueryResponse {
}
