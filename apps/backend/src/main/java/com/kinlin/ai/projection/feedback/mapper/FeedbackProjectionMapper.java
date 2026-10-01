package com.kinlin.ai.projection.feedback.mapper;

import com.kinlin.ai.entity.UserFeedback;
import com.kinlin.ai.projection.feedback.dto.FeedbackQuery;

import java.util.ArrayList;
import java.util.List;

/** Pure output adapter over persisted feedback rows; no repository, service or state access. */
public final class FeedbackProjectionMapper {
    private FeedbackProjectionMapper() { }

    public static FeedbackQuery toQuery(UserFeedback feedback) {
        return new FeedbackQuery(feedback.getId(), feedback.getUserId(), feedback.getConversationId(),
                feedback.getMessageId(), feedback.getRoleId(), feedback.getFeedbackType(),
                feedback.getRating(), feedback.getContent(), feedback.getSentiment(), feedback.getCreatedAt());
    }

    public static List<FeedbackQuery> toQuery(List<UserFeedback> feedbacks) {
        List<FeedbackQuery> projected = new ArrayList<>(feedbacks.size());
        for (UserFeedback feedback : feedbacks) {
            projected.add(toQuery(feedback));
        }
        return projected;
    }
}
