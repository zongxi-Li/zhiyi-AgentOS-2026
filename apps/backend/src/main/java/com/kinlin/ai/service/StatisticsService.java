package com.kinlin.ai.service;

import com.kinlin.ai.entity.Conversation;
import com.kinlin.ai.entity.Message;
import com.kinlin.ai.repository.ConversationRepository;
import com.kinlin.ai.repository.MessageRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * 统计服务
 * 提供对话统计、用户活跃度等数据分析功能
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class StatisticsService {

    private final ConversationRepository conversationRepository;
    private final MessageRepository messageRepository;

    /**
     * 获取用户对话统计
     */
    public Map<String, Object> getUserStatistics(UUID userId) {
        Map<String, Object> stats = new HashMap<>();
        
        // 获取用户的所有对话
        List<Conversation> conversations = conversationRepository.findByUserId(userId);
        stats.put("totalConversations", conversations.size());
        
        // 获取用户的所有消息
        List<UUID> conversationIds = conversations.stream()
                .map(Conversation::getId)
                .toList();
        List<Message> messages = conversationIds.isEmpty() ? 
                List.of() : 
                messageRepository.findAll().stream()
                        .filter(msg -> conversationIds.contains(msg.getConversationId()))
                        .toList();
        stats.put("totalMessages", messages.size());
        
        // 计算平均对话长度
        if (!conversations.isEmpty()) {
            stats.put("avgMessagesPerConversation", 
                    (double) messages.size() / conversations.size());
        } else {
            stats.put("avgMessagesPerConversation", 0.0);
        }
        
        // 统计最近7天的活跃度
        LocalDateTime sevenDaysAgo = LocalDateTime.now().minusDays(7);
        long recentMessages = messages.stream()
                .filter(msg -> msg.getCreatedAt() != null && 
                        msg.getCreatedAt().isAfter(sevenDaysAgo))
                .count();
        stats.put("recentMessages", recentMessages);
        
        // 统计最活跃的时段（简化实现）
        Map<Integer, Long> hourDistribution = new HashMap<>();
        messages.forEach(msg -> {
            if (msg.getCreatedAt() != null) {
                int hour = msg.getCreatedAt().getHour();
                hourDistribution.merge(hour, 1L, Long::sum);
            }
        });
        stats.put("hourDistribution", hourDistribution);
        
        log.debug("用户统计: userId={}, stats={}", userId, stats);
        return stats;
    }

    /**
     * 获取系统整体统计
     */
    public Map<String, Object> getSystemStatistics() {
        Map<String, Object> stats = new HashMap<>();
        
        // 总对话数
        long totalConversations = conversationRepository.count();
        stats.put("totalConversations", totalConversations);
        
        // 总消息数
        long totalMessages = messageRepository.count();
        stats.put("totalMessages", totalMessages);
        
        // 活跃用户数（最近7天有对话的用户）
        LocalDateTime sevenDaysAgo = LocalDateTime.now().minusDays(7);
        long activeUsers = conversationRepository.findAll().stream()
                .filter(conv -> conv.getCreatedAt() != null && 
                        conv.getCreatedAt().isAfter(sevenDaysAgo))
                .map(Conversation::getUserId)
                .distinct()
                .count();
        stats.put("activeUsers", activeUsers);
        
        // 平均对话长度
        if (totalConversations > 0) {
            stats.put("avgMessagesPerConversation", 
                    (double) totalMessages / totalConversations);
        } else {
            stats.put("avgMessagesPerConversation", 0.0);
        }
        
        return stats;
    }

    /**
     * 获取角色使用统计
     */
    public Map<String, Object> getRoleStatistics(UUID userId) {
        Map<String, Object> stats = new HashMap<>();
        
        List<Conversation> conversations = conversationRepository.findByUserId(userId);
        
        // 统计各角色的使用次数
        Map<UUID, Long> roleUsage = new HashMap<>();
        conversations.forEach(conv -> {
            if (conv.getRoleId() != null) {
                roleUsage.merge(conv.getRoleId(), 1L, Long::sum);
            }
        });
        
        stats.put("roleUsage", roleUsage);
        stats.put("mostUsedRole", roleUsage.entrySet().stream()
                .max(Map.Entry.comparingByValue())
                .map(Map.Entry::getKey)
                .orElse(null));
        
        return stats;
    }
}

