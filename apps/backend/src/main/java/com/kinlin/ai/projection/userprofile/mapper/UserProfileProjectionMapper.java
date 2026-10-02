package com.kinlin.ai.projection.userprofile.mapper;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import com.kinlin.ai.projection.common.mapper.QueryWire;
import com.kinlin.ai.projection.userprofile.dto.ProfileRecommendationsQuery;
import com.kinlin.ai.projection.userprofile.dto.UserProfileQuery;

import static com.kinlin.ai.projection.common.mapper.QueryWire.integer;
import static com.kinlin.ai.projection.common.mapper.QueryWire.invalid;
import static com.kinlin.ai.projection.common.mapper.QueryWire.text;
import static com.kinlin.ai.projection.common.mapper.QueryWire.texts;

/**
 * Pure whitelist mapping from the in-process UserProfileService output to the
 * typed profile DTOs. No I/O, no recomputation: usage counts and role favorites
 * are the service's own aggregates. The dynamic per-role usage map becomes typed
 * role/count rows.
 */
public final class UserProfileProjectionMapper {
    private UserProfileProjectionMapper() {
    }

    public static UserProfileQuery profile(Map<String, Object> wire) {
        if (!(wire.get("userId") instanceof String userId) || userId.isBlank()) {
            throw invalid();
        }
        Object usage = wire.get("roleUsageCount");
        List<UserProfileQuery.RoleCountQuery> rows = new ArrayList<>();
        if (usage instanceof Map<?, ?> map) {
            for (Map.Entry<?, ?> entry : map.entrySet()) {
                if (!(entry.getValue() instanceof Number count)) {
                    throw invalid();
                }
                rows.add(new UserProfileQuery.RoleCountQuery(
                        String.valueOf(entry.getKey()), count.longValue()));
            }
        }
        return new UserProfileQuery(
                userId,
                text(wire, "username"),
                text(wire, "email"),
                integer(wire, "conversationCount"),
                text(wire, "favoriteRoleId"),
                text(wire, "favoriteRoleName"),
                rows.isEmpty() ? null : rows,
                text(wire, "activityLevel"));
    }

    public static ProfileRecommendationsQuery recommendations(Map<String, Object> wire) {
        List<String> roles = wire.get("recommendedRoles") instanceof java.util.Collection<?> collection
                ? collection.stream().map(String::valueOf).toList()
                : null;
        if (wire.get("topics") == null) {
            throw invalid();
        }
        return new ProfileRecommendationsQuery(roles, texts(wire.get("topics")));
    }
}
