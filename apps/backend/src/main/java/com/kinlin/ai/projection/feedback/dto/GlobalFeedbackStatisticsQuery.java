package com.kinlin.ai.projection.feedback.dto;

import java.util.List;

/**
 * 全局反馈统计查询投影。字段语义与 {@link UserFeedbackStatisticsQuery} 一致：
 * averageRating 保留 0.0 缺省；feedbackTypeCount 由动态键 Map 迁移为按分类键
 * 字典序排序的显式列表。
 */
public record GlobalFeedbackStatisticsQuery(
        long totalFeedbacks,
        double averageRating,
        List<CategoryCountQuery> feedbackTypeCount
) { }
