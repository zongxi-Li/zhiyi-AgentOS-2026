package com.kinlin.ai.controller;

import com.kinlin.ai.entity.UserFeedback;
import com.kinlin.ai.exception.ResourceNotFoundException;
import com.kinlin.ai.projection.feedback.dto.FeedbackQuery;
import com.kinlin.ai.projection.feedback.mapper.FeedbackProjectionMapper;
import com.kinlin.ai.security.AuthenticatedUser;
import com.kinlin.ai.service.UserFeedbackService;
import lombok.Data;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * 用户反馈控制器
 */
@RestController
@RequestMapping("/api/feedback")
@RequiredArgsConstructor
public class UserFeedbackController {

    private final UserFeedbackService feedbackService;

    /**
     * 提交反馈
     */
    @PostMapping
    public ResponseEntity<Map<String, Object>> submitFeedback(@RequestBody FeedbackRequest request) {
        UserFeedback feedback = feedbackService.createFeedback(
                request.getUserId(),
                request.getConversationId(),
                request.getMessageId(),
                request.getRoleId(),
                request.getFeedbackType(),
                request.getRating(),
                request.getContent()
        );

        Map<String, Object> response = new HashMap<>();
        response.put("message", "反馈已提交");
        response.put("feedbackId", feedback.getId());
        return ResponseEntity.ok(response);
    }

    /**
     * 获取用户反馈列表（路径参数仅为兼容保留，实际以认证身份为准）
     */
    @GetMapping("/user/{userId}")
    public ResponseEntity<List<FeedbackQuery>> getUserFeedbacks(@PathVariable UUID userId) {
        List<UserFeedback> feedbacks = feedbackService.getUserFeedbacks(requireCurrentUserId());
        return ResponseEntity.ok(FeedbackProjectionMapper.toQuery(feedbacks));
    }

    /**
     * 获取用户反馈统计（路径参数仅为兼容保留，实际以认证身份为准）
     */
    @GetMapping("/user/{userId}/statistics")
    public ResponseEntity<UserFeedbackService.FeedbackStatistics> getUserFeedbackStatistics(
            @PathVariable UUID userId
    ) {
        UserFeedbackService.FeedbackStatistics statistics =
                feedbackService.getFeedbackStatistics(requireCurrentUserId());
        return ResponseEntity.ok(statistics);
    }

    /**
     * 获取全局反馈统计
     */
    @GetMapping("/statistics")
    public ResponseEntity<UserFeedbackService.GlobalFeedbackStatistics> getGlobalStatistics() {
        UserFeedbackService.GlobalFeedbackStatistics statistics =
                feedbackService.getGlobalStatistics();
        return ResponseEntity.ok(statistics);
    }

    /**
     * 反馈请求DTO
     */
    @Data
    public static class FeedbackRequest {
        private UUID userId;
        private UUID conversationId;
        private UUID messageId;
        private UUID roleId;
        private String feedbackType; // quality, relevance, helpfulness, other
        private Integer rating; // 1-5
        private String content;
    }

    private UUID requireCurrentUserId() {
        return AuthenticatedUser.currentUserId()
                .orElseThrow(() -> new ResourceNotFoundException("未认证，无法获取反馈数据"));
    }
}

