package com.kinlin.ai.projection.feedback.mapper;

import com.kinlin.ai.projection.feedback.dto.CategoryCountQuery;
import com.kinlin.ai.projection.feedback.dto.GlobalFeedbackStatisticsQuery;
import com.kinlin.ai.projection.feedback.dto.UserFeedbackStatisticsQuery;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * Pure output adapter over feedback aggregate counters; converts the dynamic category-key
 * maps into lexicographically ordered explicit lists. No repository, service or state access.
 */
public final class FeedbackStatisticsProjectionMapper {
    private FeedbackStatisticsProjectionMapper() { }

    public static UserFeedbackStatisticsQuery toQuery(UUID userId, long totalFeedbacks, double averageRating,
            Map<String, Long> feedbackTypeCount, Map<String, Long> sentimentCount) {
        return new UserFeedbackStatisticsQuery(userId, totalFeedbacks, averageRating,
                toCategoryCounts(feedbackTypeCount), toCategoryCounts(sentimentCount));
    }

    public static GlobalFeedbackStatisticsQuery toQuery(long totalFeedbacks, double averageRating,
            Map<String, Long> feedbackTypeCount) {
        return new GlobalFeedbackStatisticsQuery(totalFeedbacks, averageRating, toCategoryCounts(feedbackTypeCount));
    }

    private static List<CategoryCountQuery> toCategoryCounts(Map<String, Long> counts) {
        List<Map.Entry<String, Long>> entries = new ArrayList<>(counts.entrySet());
        entries.sort(Map.Entry.comparingByKey());
        List<CategoryCountQuery> categories = new ArrayList<>(entries.size());
        for (Map.Entry<String, Long> entry : entries) {
            categories.add(new CategoryCountQuery(entry.getKey(), entry.getValue()));
        }
        return categories;
    }
}
