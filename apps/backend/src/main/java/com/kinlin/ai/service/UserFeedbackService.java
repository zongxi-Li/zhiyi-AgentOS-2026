package com.kinlin.ai.service;

import com.kinlin.ai.entity.UserFeedback;
import com.kinlin.ai.repository.UserFeedbackRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.*;
import java.util.stream.Collectors;

/**
 * 用户反馈服务
 * 收集和分析用户反馈，用于系统优化
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class UserFeedbackService {

    private final UserFeedbackRepository feedbackRepository;

    /**
     * 创建反馈
     */
    @Transactional
    public UserFeedback createFeedback(
            UUID userId,
            UUID conversationId,
            UUID messageId,
            UUID roleId,
            String feedbackType,
            Integer rating,
            String content
    ) {
        UserFeedback feedback = new UserFeedback();
        feedback.setUserId(userId);
        feedback.setConversationId(conversationId);
        feedback.setMessageId(messageId);
        feedback.setRoleId(roleId);
        feedback.setFeedbackType(feedbackType);
        feedback.setRating(rating);
        feedback.setContent(content);

        // 自动分析情感
        if (content != null && !content.isEmpty()) {
            feedback.setSentiment(analyzeSentiment(content, rating));
        } else if (rating != null) {
            feedback.setSentiment(analyzeSentimentFromRating(rating));
        }

        UserFeedback saved = feedbackRepository.save(feedback);
        log.info("用户反馈已创建: userId={}, type={}, rating={}", userId, feedbackType, rating);
        return saved;
    }

    /**
     * 获取用户反馈列表
     */
    public List<UserFeedback> getUserFeedbacks(UUID userId) {
        return feedbackRepository.findByUserId(userId);
    }

    /**
     * 获取反馈统计
     */
    public FeedbackStatistics getFeedbackStatistics(UUID userId) {
        FeedbackStatistics stats = new FeedbackStatistics();
        stats.setUserId(userId);
        stats.setTotalFeedbacks(feedbackRepository.countByUserId(userId));
        
        Double avgRating = feedbackRepository.getAverageRatingByUserId(userId);
        stats.setAverageRating(avgRating != null ? avgRating : 0.0);

        // 统计各类型反馈
        List<UserFeedback> feedbacks = feedbackRepository.findByUserId(userId);
        Map<String, Long> typeCount = feedbacks.stream()
                .collect(Collectors.groupingBy(
                        UserFeedback::getFeedbackType,
                        Collectors.counting()
                ));
        stats.setFeedbackTypeCount(typeCount);

        // 统计情感分布
        Map<String, Long> sentimentCount = feedbacks.stream()
                .filter(f -> f.getSentiment() != null)
                .collect(Collectors.groupingBy(
                        UserFeedback::getSentiment,
                        Collectors.counting()
                ));
        stats.setSentimentCount(sentimentCount);

        return stats;
    }

    /**
     * 获取全局反馈统计
     */
    public GlobalFeedbackStatistics getGlobalStatistics() {
        GlobalFeedbackStatistics stats = new GlobalFeedbackStatistics();
        stats.setTotalFeedbacks(feedbackRepository.count());

        // 统计各类型反馈
        List<Object[]> typeCounts = feedbackRepository.countByFeedbackType();
        Map<String, Long> typeCountMap = new HashMap<>();
        for (Object[] row : typeCounts) {
            typeCountMap.put((String) row[0], (Long) row[1]);
        }
        stats.setFeedbackTypeCount(typeCountMap);

        // 计算平均评分
        List<UserFeedback> allFeedbacks = feedbackRepository.findAll();
        OptionalDouble avgRating = allFeedbacks.stream()
                .filter(f -> f.getRating() != null)
                .mapToInt(UserFeedback::getRating)
                .average();
        stats.setAverageRating(avgRating.isPresent() ? avgRating.getAsDouble() : 0.0);

        return stats;
    }

    /**
     * 分析情感（简单实现）
     */
    private String analyzeSentiment(String content, Integer rating) {
        if (rating != null) {
            return analyzeSentimentFromRating(rating);
        }

        // 简单关键词分析
        String lowerContent = content.toLowerCase();
        int positiveWords = countWords(lowerContent, Arrays.asList("好", "不错", "满意", "喜欢", "有用", "帮助"));
        int negativeWords = countWords(lowerContent, Arrays.asList("差", "不好", "不满意", "没用", "错误", "问题"));

        if (positiveWords > negativeWords) {
            return "positive";
        } else if (negativeWords > positiveWords) {
            return "negative";
        } else {
            return "neutral";
        }
    }

    /**
     * 根据评分分析情感
     */
    private String analyzeSentimentFromRating(Integer rating) {
        if (rating >= 4) {
            return "positive";
        } else if (rating <= 2) {
            return "negative";
        } else {
            return "neutral";
        }
    }

    /**
     * 统计关键词出现次数
     */
    private int countWords(String text, List<String> keywords) {
        return (int) keywords.stream()
                .filter(text::contains)
                .count();
    }

    /**
     * 反馈统计数据类
     */
    public static class FeedbackStatistics {
        private UUID userId;
        private long totalFeedbacks;
        private double averageRating;
        private Map<String, Long> feedbackTypeCount;
        private Map<String, Long> sentimentCount;

        // Getters and Setters
        public UUID getUserId() {
            return userId;
        }

        public void setUserId(UUID userId) {
            this.userId = userId;
        }

        public long getTotalFeedbacks() {
            return totalFeedbacks;
        }

        public void setTotalFeedbacks(long totalFeedbacks) {
            this.totalFeedbacks = totalFeedbacks;
        }

        public double getAverageRating() {
            return averageRating;
        }

        public void setAverageRating(double averageRating) {
            this.averageRating = averageRating;
        }

        public Map<String, Long> getFeedbackTypeCount() {
            return feedbackTypeCount;
        }

        public void setFeedbackTypeCount(Map<String, Long> feedbackTypeCount) {
            this.feedbackTypeCount = feedbackTypeCount;
        }

        public Map<String, Long> getSentimentCount() {
            return sentimentCount;
        }

        public void setSentimentCount(Map<String, Long> sentimentCount) {
            this.sentimentCount = sentimentCount;
        }
    }

    /**
     * 全局反馈统计数据类
     */
    public static class GlobalFeedbackStatistics {
        private long totalFeedbacks;
        private double averageRating;
        private Map<String, Long> feedbackTypeCount;

        // Getters and Setters
        public long getTotalFeedbacks() {
            return totalFeedbacks;
        }

        public void setTotalFeedbacks(long totalFeedbacks) {
            this.totalFeedbacks = totalFeedbacks;
        }

        public double getAverageRating() {
            return averageRating;
        }

        public void setAverageRating(double averageRating) {
            this.averageRating = averageRating;
        }

        public Map<String, Long> getFeedbackTypeCount() {
            return feedbackTypeCount;
        }

        public void setFeedbackTypeCount(Map<String, Long> feedbackTypeCount) {
            this.feedbackTypeCount = feedbackTypeCount;
        }
    }
}

