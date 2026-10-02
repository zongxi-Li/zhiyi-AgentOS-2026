package com.kinlin.ai.projection.statistics.mapper;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import com.kinlin.ai.projection.common.mapper.QueryWire;
import com.kinlin.ai.projection.statistics.dto.RoleStatisticsQuery;
import com.kinlin.ai.projection.statistics.dto.SystemStatisticsQuery;
import com.kinlin.ai.projection.statistics.dto.UserStatisticsQuery;

import static com.kinlin.ai.projection.common.mapper.QueryWire.decimal;
import static com.kinlin.ai.projection.common.mapper.QueryWire.invalid;
import static com.kinlin.ai.projection.common.mapper.QueryWire.integer;

/**
 * Pure whitelist mapping from the in-process StatisticsService maps to the typed
 * statistics DTOs. No I/O, no recomputation: counts and averages are the
 * service's own aggregates. The dynamic hour-distribution and role-usage maps
 * become typed rows (hour/roleId is data, never a wire key).
 */
public final class StatisticsProjectionMapper {
    private StatisticsProjectionMapper() {
    }

    public static UserStatisticsQuery userStatistics(Map<String, Object> wire) {
        if (!(wire.get("totalConversations") instanceof Number)
                || !(wire.get("totalMessages") instanceof Number)) {
            throw invalid();
        }
        return new UserStatisticsQuery(
                integer(wire, "totalConversations"),
                integer(wire, "totalMessages"),
                decimal(wire, "avgMessagesPerConversation"),
                integer(wire, "recentMessages"),
                hourRows(wire.get("hourDistribution")));
    }

    public static SystemStatisticsQuery systemStatistics(Map<String, Object> wire) {
        if (!(wire.get("totalConversations") instanceof Number)
                || !(wire.get("totalMessages") instanceof Number)) {
            throw invalid();
        }
        return new SystemStatisticsQuery(
                integer(wire, "totalConversations"),
                integer(wire, "totalMessages"),
                integer(wire, "activeUsers"),
                decimal(wire, "avgMessagesPerConversation"));
    }

    public static RoleStatisticsQuery roleStatistics(Map<String, Object> wire) {
        if (!(wire.get("roleUsage") instanceof Map<?, ?> usage)) {
            throw invalid();
        }
        List<RoleStatisticsQuery.RoleUsageQuery> rows = new ArrayList<>();
        for (Map.Entry<?, ?> entry : usage.entrySet()) {
            if (!(entry.getValue() instanceof Number count)) {
                throw invalid();
            }
            rows.add(new RoleStatisticsQuery.RoleUsageQuery(
                    String.valueOf(entry.getKey()), count.longValue()));
        }
        Object mostUsed = wire.get("mostUsedRole");
        return new RoleStatisticsQuery(
                List.copyOf(rows),
                mostUsed == null ? null : String.valueOf(mostUsed));
    }

    private static List<UserStatisticsQuery.HourCountQuery> hourRows(Object raw) {
        if (!(raw instanceof Map<?, ?> map)) {
            return null;
        }
        List<UserStatisticsQuery.HourCountQuery> rows = new ArrayList<>();
        for (Map.Entry<?, ?> entry : map.entrySet()) {
            if (!(entry.getValue() instanceof Number count)) {
                throw invalid();
            }
            rows.add(new UserStatisticsQuery.HourCountQuery(
                    Integer.valueOf(String.valueOf(entry.getKey())), count.longValue()));
        }
        return rows;
    }
}
