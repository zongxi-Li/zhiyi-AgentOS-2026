package com.kinlin.ai.projection.statistics.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

import java.util.List;

/**
 * Typed per-user role usage statistics: one row per used role plus the most used
 * role (null when the user has no conversations with a role bound).
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record RoleStatisticsQuery(
        List<RoleUsageQuery> roleUsage,
        String mostUsedRole
) implements QueryResponse {

    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record RoleUsageQuery(
            String roleId,
            Long count
    ) implements QueryResponse {
    }
}
