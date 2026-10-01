package com.kinlin.ai.projection.mission.dto;

import com.kinlin.ai.projection.common.dto.QueryResponse;
import java.util.List;

/**
 * Mission 列表查询投影。沿用 Mission 详情的字段规则：不携带 owner 身份（userId）
 * 与任何内部模型；时间字符串原样保留上游偏移与精度。
 */
public record MissionListQuery(List<Item> items, long total, int page, int pageSize, String source)
        implements QueryResponse {
    public MissionListQuery {
        items = List.copyOf(items);
    }

    public record Item(String missionId, String title, String description, String status,
                       String latestRunId, String latestRunStatus, String createdAt, String updatedAt,
                       int runCount) { }
}
