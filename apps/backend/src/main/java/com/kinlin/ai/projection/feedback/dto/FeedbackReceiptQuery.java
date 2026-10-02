package com.kinlin.ai.projection.feedback.dto;

import java.util.UUID;

/**
 * POST /api/feedback 提交回执的显式 typed 投影：字段名、类型与文案保持旧
 * Map 回执（{"message":"反馈已提交","feedbackId":...}）逐字段一致。
 */
public record FeedbackReceiptQuery(String message, UUID feedbackId) { }
