package com.kinlin.ai.controller;

import com.kinlin.ai.service.UserProfileService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

/**
 * 用户画像控制器
 */
@RestController
@RequestMapping("/profile")
@RequiredArgsConstructor
public class UserProfileController {

    private final UserProfileService userProfileService;

    /**
     * 获取用户画像
     */
    @GetMapping("/{userId}")
    public ResponseEntity<Map<String, Object>> getUserProfile(@PathVariable UUID userId) {
        UserProfileService.UserProfile userProfile = userProfileService.buildUserProfile(userId);
        Map<String, Object> profile = new HashMap<>();
        profile.put("userId", userProfile.getUserId());
        profile.put("username", userProfile.getUsername());
        profile.put("email", userProfile.getEmail());
        profile.put("conversationCount", userProfile.getConversationCount());
        profile.put("favoriteRoleId", userProfile.getFavoriteRoleId());
        profile.put("favoriteRoleName", userProfile.getFavoriteRoleName());
        profile.put("roleUsageCount", userProfile.getRoleUsageCount());
        profile.put("activityLevel", userProfile.getActivityLevel());
        return ResponseEntity.ok(profile);
    }

    /**
     * 获取个性化推荐
     */
    @GetMapping("/{userId}/recommendations")
    public ResponseEntity<Map<String, Object>> getRecommendations(@PathVariable UUID userId) {
        Map<String, Object> recommendations = userProfileService.getPersonalizedRecommendations(userId);
        return ResponseEntity.ok(recommendations);
    }
}
