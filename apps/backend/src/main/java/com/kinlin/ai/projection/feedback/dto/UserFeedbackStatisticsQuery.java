package com.kinlin.ai.projection.feedback.dto;

import java.util.List;
import java.util.UUID;

/**
 * 用户反馈统计查询投影。totalFeedbacks/averageRating 沿用既有数值语义；
 * averageRating 保留旧响应的 0.0 缺省（无反馈或无评分时输出 0.0，不改为 null）。
 * feedbackTypeCount/sentimentCount 由旧 Map&lt;String,Long&gt; 动态键迁移为按分类键
 * 字典序排序的显式列表，自定义分类原样保留。
 */
public record UserFeedbackStatisticsQuery(
        UUID userId,
        long totalFeedbacks,
        double averageRating,
        List<CategoryCountQuery> feedbackTypeCount,
        List<CategoryCountQuery> sentimentCount
) { }
