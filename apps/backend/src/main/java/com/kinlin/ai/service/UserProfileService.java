package com.kinlin.ai.service;

import com.kinlin.ai.entity.User;
import com.kinlin.ai.repository.RoleRepository;
import lombok.Data;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

/**
 * 用户画像服务
 * 用于构建用户画像和个性化推荐
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class UserProfileService {

    private final UserService userService;
    private final ConversationService conversationService;
    private final RoleRepository roleRepository;

    /**
     * 用户画像数据类
     */
    @Data
    public static class UserProfile {
        private UUID userId;
        private String username;
        private String email;
        private Integer conversationCount;
        private UUID favoriteRoleId;
        private String favoriteRoleName;
        private Map<String, Integer> roleUsageCount;
        private String activityLevel;
    }

    /**
     * 构建用户画像
     */
    public UserProfile buildUserProfile(UUID userId) {
        UserProfile profile = new UserProfile();
        profile.setUserId(userId);
        
        // 获取用户基本信息
        userService.getUserById(userId).ifPresent(user -> {
            profile.setUsername(user.getUsername());
            profile.setEmail(user.getEmail());
        });
        
        // 获取对话统计
        var conversations = conversationService.getUserConversations(userId);
        profile.setConversationCount(conversations.size());
        
        // 获取常用角色
        Map<String, Integer> roleUsage = new HashMap<>();
        conversations.forEach(conv -> {
            if (conv.getRoleId() != null) {
                roleUsage.merge(conv.getRoleId().toString(), 1, Integer::sum);
            }
        });
        profile.setRoleUsageCount(roleUsage);
        
        // 找出最常用的角色
        if (!roleUsage.isEmpty()) {
            String favoriteRoleIdStr = roleUsage.entrySet().stream()
                    .max(Map.Entry.comparingByValue())
                    .map(Map.Entry::getKey)
                    .orElse(null);
            if (favoriteRoleIdStr != null) {
                try {
                    UUID favoriteRoleId = UUID.fromString(favoriteRoleIdStr);
                    profile.setFavoriteRoleId(favoriteRoleId);
                    // 获取角色名称
                    roleRepository.findById(favoriteRoleId).ifPresent(role -> {
                        profile.setFavoriteRoleName(role.getName());
                    });
                } catch (IllegalArgumentException e) {
                    log.warn("Invalid UUID format: {}", favoriteRoleIdStr);
                }
            }
        }
        
        // 计算活跃度
        int count = profile.getConversationCount() != null ? profile.getConversationCount() : 0;
        if (count > 100) {
            profile.setActivityLevel("very_active");
        } else if (count > 50) {
            profile.setActivityLevel("active");
        } else if (count > 10) {
            profile.setActivityLevel("moderate");
        } else {
            profile.setActivityLevel("low");
        }
        
        log.debug("构建用户画像: userId={}, profile={}", userId, profile);
        return profile;
    }

    /**
     * 获取个性化推荐
     */
    public Map<String, Object> getPersonalizedRecommendations(UUID userId) {
        UserProfile profile = buildUserProfile(userId);
        Map<String, Object> recommendations = new HashMap<>();
        
        // 基于用户画像推荐角色
        if (profile.getRoleUsageCount() != null && !profile.getRoleUsageCount().isEmpty()) {
            recommendations.put("recommendedRoles", profile.getRoleUsageCount().keySet());
        }
        
        // 推荐对话主题（简化实现）
        recommendations.put("topics", java.util.List.of("技术", "生活", "学习"));
        
        return recommendations;
    }
}
