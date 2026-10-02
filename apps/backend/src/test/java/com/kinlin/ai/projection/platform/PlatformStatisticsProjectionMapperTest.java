package com.kinlin.ai.projection.platform;

import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.projection.statistics.mapper.StatisticsProjectionMapper;
import com.kinlin.ai.projection.userprofile.mapper.UserProfileProjectionMapper;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Wire contracts for the platform statistics and profile projections: the
 * service's own aggregates pass through, dynamic maps become typed rows, and
 * damaged service output fails loudly instead of faking zero stats.
 */
class PlatformStatisticsProjectionMapperTest {
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private static Set<String> keys(JsonNode node) {
        Set<String> names = new LinkedHashSet<>();
        node.fieldNames().forEachRemaining(names::add);
        return names;
    }

    private static JsonNode json(Object mapped) throws Exception {
        return MAPPER.readTree(MAPPER.writeValueAsString(mapped));
    }

    private static Map<String, Object> row(Object... keyValues) {
        Map<String, Object> result = new LinkedHashMap<>();
        for (int index = 0; index < keyValues.length; index += 2) {
            result.put(String.valueOf(keyValues[index]), keyValues[index + 1]);
        }
        return result;
    }

    @Test
    void userStatisticsKeepServiceAggregatesAndHourRows() throws Exception {
        JsonNode body = json(StatisticsProjectionMapper.userStatistics(row(
                "totalConversations", 12, "totalMessages", 345,
                "avgMessagesPerConversation", 28.75, "recentMessages", 40,
                "hourDistribution", row(9, 12L, 21, 7L))));
        assertEquals(Set.of("totalConversations", "totalMessages", "avgMessagesPerConversation",
                "recentMessages", "hourDistribution"), keys(body));
        assertEquals(2, body.path("hourDistribution").size());
        assertEquals(12, body.path("hourDistribution").get(0).path("count").asLong());
        assertEquals(28.75, body.path("avgMessagesPerConversation").asDouble());
    }

    @Test
    void systemAndRoleStatisticsKeepTheirWhitelists() throws Exception {
        JsonNode system = json(StatisticsProjectionMapper.systemStatistics(row(
                "totalConversations", 100, "totalMessages", 2000,
                "activeUsers", 7, "avgMessagesPerConversation", 20.0)));
        assertEquals(Set.of("totalConversations", "totalMessages", "activeUsers",
                "avgMessagesPerConversation"), keys(system));
        JsonNode roles = json(StatisticsProjectionMapper.roleStatistics(row(
                "roleUsage", Map.of("11111111-1111-1111-1111-111111111111", 3L,
                        "22222222-2222-2222-2222-222222222222", 5L),
                "mostUsedRole", "22222222-2222-2222-2222-222222222222")));
        assertEquals(Set.of("roleUsage", "mostUsedRole"), keys(roles));
        assertEquals(2, roles.path("roleUsage").size());
        // A most-used role of null (no conversations) stays an honest null.
        JsonNode empty = json(StatisticsProjectionMapper.roleStatistics(row(
                "roleUsage", Map.of(), "mostUsedRole", null)));
        assertFalse(empty.has("mostUsedRole"), "a null most-used role stays absent, not fake");
    }

    @Test
    void damagedStatisticsFailLoudlyInsteadOfFakingZeroes() {
        assertThrows(IllegalArgumentException.class,
                () -> StatisticsProjectionMapper.userStatistics(Map.of()));
        assertThrows(IllegalArgumentException.class,
                () -> StatisticsProjectionMapper.systemStatistics(row("totalConversations", 1)));
        assertThrows(IllegalArgumentException.class,
                () -> StatisticsProjectionMapper.roleStatistics(Map.of()));
        assertThrows(IllegalArgumentException.class,
                () -> StatisticsProjectionMapper.roleStatistics(row(
                        "roleUsage", Map.of("r", "not-a-number"), "mostUsedRole", null)));
    }

    @Test
    void userProfileKeepsIdentityFieldsAndRoleRows() throws Exception {
        JsonNode body = json(UserProfileProjectionMapper.profile(row(
                "userId", "11111111-1111-1111-1111-111111111111",
                "username", "alice", "email", "alice@example.com",
                "conversationCount", 9, "favoriteRoleId", "22222222-2222-2222-2222-222222222222",
                "favoriteRoleName", "分析师", "roleUsageCount", Map.of(
                        "22222222-2222-2222-2222-222222222222", 6),
                "activityLevel", "high")));
        assertEquals(Set.of("userId", "username", "email", "conversationCount", "favoriteRoleId",
                "favoriteRoleName", "roleUsageCount", "activityLevel"), keys(body));
        assertEquals(6, body.path("roleUsageCount").get(0).path("count").asLong());
        // An empty role map is an absent list, not a fabricated row.
        JsonNode bare = json(UserProfileProjectionMapper.profile(row(
                "userId", "u", "roleUsageCount", Map.of())));
        assertFalse(bare.has("roleUsageCount"));
    }

    @Test
    void recommendationsKeepTheirReaderLists() throws Exception {
        JsonNode body = json(UserProfileProjectionMapper.recommendations(row(
                "recommendedRoles", List.of("r1", "r2"), "topics", List.of("技术", "生活", "学习"))));
        assertEquals(Set.of("recommendedRoles", "topics"), keys(body));
        assertEquals(3, body.path("topics").size());
        assertThrows(IllegalArgumentException.class,
                () -> UserProfileProjectionMapper.recommendations(row("recommendedRoles", List.of("r1"))));
    }
}
