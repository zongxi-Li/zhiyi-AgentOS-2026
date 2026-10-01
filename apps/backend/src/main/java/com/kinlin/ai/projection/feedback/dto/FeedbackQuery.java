package com.kinlin.ai.projection.feedback.dto;

import java.time.LocalDateTime;
import java.util.UUID;

/**
 * 反馈列表查询投影。字段与既有 UserFeedback 响应逐一对齐（camelCase wire 名不变），
 * 仅显式声明公共列；实体本身不再离开 Controller。
 */
public record FeedbackQuery(
        UUID id,
        UUID userId,
        UUID conversationId,
        UUID messageId,
        UUID roleId,
        String feedbackType,
        Integer rating,
        String content,
        String sentiment,
        LocalDateTime createdAt
) { }
