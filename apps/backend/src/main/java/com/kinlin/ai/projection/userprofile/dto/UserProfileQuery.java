package com.kinlin.ai.projection.userprofile.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

import java.util.List;

/**
 * Typed user profile over the UserProfileService wire: identity fields plus the
 * aggregated usage summary. The per-role usage counts keep their reader meaning
 * as typed role/count rows.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record UserProfileQuery(
        String userId,
        String username,
        String email,
        Long conversationCount,
        String favoriteRoleId,
        String favoriteRoleName,
        List<RoleCountQuery> roleUsageCount,
        String activityLevel
) implements QueryResponse {

    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record RoleCountQuery(
            String roleId,
            Long count
    ) implements QueryResponse {
    }
}
