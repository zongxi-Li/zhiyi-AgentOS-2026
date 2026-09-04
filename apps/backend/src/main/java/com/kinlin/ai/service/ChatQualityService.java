package com.kinlin.ai.service;

import com.kinlin.ai.entity.Message;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.regex.Pattern;

/**
 * 对话质量评估服务
 */
@Slf4j
@Service
public class ChatQualityService {

    /**
     * 评估对话质量
     */
    public QualityScore assessQuality(List<Message> messages) {
        if (messages.isEmpty()) {
            return new QualityScore(0, "无对话内容");
        }

        double coherence = assessCoherence(messages);
        double relevance = assessRelevance(messages);
        double completeness = assessCompleteness(messages);

        double overallScore = (coherence + relevance + completeness) / 3.0;

        return new QualityScore(overallScore, generateFeedback(coherence, relevance, completeness));
    }

    /**
     * 评估对话连贯性
     */
    private double assessCoherence(List<Message> messages) {
        if (messages.size() < 2) {
            return 0.5;
        }

        // 简单的连贯性检查：检查是否有上下文关联词
        int coherenceCount = 0;
        for (int i = 1; i < messages.size(); i++) {
            String prevContent = messages.get(i - 1).getContent().toLowerCase();
            String currContent = messages.get(i).getContent().toLowerCase();

            // 检查是否有上下文关联
            if (hasContextualLink(prevContent, currContent)) {
                coherenceCount++;
            }
        }

        return Math.min(1.0, coherenceCount / (double) (messages.size() - 1));
    }

    /**
     * 评估相关性
     */
    private double assessRelevance(List<Message> messages) {
        // 简化实现：检查消息长度和内容质量
        long validMessages = messages.stream()
                .filter(msg -> msg.getContent() != null && msg.getContent().length() > 5)
                .count();

        return validMessages / (double) messages.size();
    }

    /**
     * 评估完整性
     */
    private double assessCompleteness(List<Message> messages) {
        // 检查是否有完整的问答对
        long userMessages = messages.stream()
                .filter(msg -> msg.getRole() == Message.MessageRole.USER)
                .count();

        long assistantMessages = messages.stream()
                .filter(msg -> msg.getRole() == Message.MessageRole.ASSISTANT)
                .count();

        if (userMessages == 0 || assistantMessages == 0) {
            return 0.3;
        }

        double ratio = Math.min(userMessages, assistantMessages) / 
                      (double) Math.max(userMessages, assistantMessages);
        return ratio;
    }

    /**
     * 检查上下文关联
     */
    private boolean hasContextualLink(String prev, String curr) {
        // 检查是否有代词、关联词等
        String[] contextualWords = {"这", "那", "它", "他", "她", "它们", "这个", "那个",
                "因此", "所以", "但是", "然而", "另外", "而且"};
        
        for (String word : contextualWords) {
            if (curr.contains(word)) {
                return true;
            }
        }

        // 检查是否有重复的关键词
        String[] prevWords = prev.split("\\s+");
        for (String word : prevWords) {
            if (word.length() > 2 && curr.contains(word)) {
                return true;
            }
        }

        return false;
    }

    /**
     * 生成反馈
     */
    private String generateFeedback(double coherence, double relevance, double completeness) {
        StringBuilder feedback = new StringBuilder();
        
        if (coherence < 0.5) {
            feedback.append("对话连贯性有待提升。");
        }
        if (relevance < 0.5) {
            feedback.append("回答相关性需要加强。");
        }
        if (completeness < 0.5) {
            feedback.append("对话完整性不足。");
        }
        
        if (feedback.length() == 0) {
            feedback.append("对话质量良好。");
        }
        
        return feedback.toString();
    }

    /**
     * 质量评分
     */
    public record QualityScore(double score, String feedback) {
        // score: 0.0 - 1.0
    }
}

