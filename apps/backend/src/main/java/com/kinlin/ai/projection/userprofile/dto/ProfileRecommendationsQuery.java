package com.kinlin.ai.projection.userprofile.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

import java.util.List;

/** Typed personalized recommendations over the UserProfileService wire. */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ProfileRecommendationsQuery(
        List<String> recommendedRoles,
        List<String> topics
) implements QueryResponse {
}
