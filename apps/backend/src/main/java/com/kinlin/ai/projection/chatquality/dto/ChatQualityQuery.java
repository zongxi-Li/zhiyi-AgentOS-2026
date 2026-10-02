package com.kinlin.ai.projection.chatquality.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/**
 * Typed chat quality assessment over the ChatQualityService wire: the service's
 * own score and feedback plus the assessed message count, never recomputed.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ChatQualityQuery(
        Double score,
        String feedback,
        Long messageCount
) implements QueryResponse {
}
