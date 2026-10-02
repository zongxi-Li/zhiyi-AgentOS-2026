package com.kinlin.ai.controller;

import com.kinlin.ai.projection.userprofile.dto.ProfileRecommendationsQuery;
import com.kinlin.ai.projection.userprofile.dto.UserProfileQuery;
import com.kinlin.ai.projection.userprofile.mapper.UserProfileProjectionMapper;
import com.kinlin.ai.service.UserProfileService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.LinkedHashMap;
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
    public ResponseEntity<UserProfileQuery> getUserProfile(@PathVariable UUID userId) {
        UserProfileService.UserProfile userProfile = userProfileService.buildUserProfile(userId);
        Map<String, Object> wire = new LinkedHashMap<>();
        wire.put("userId", String.valueOf(userProfile.getUserId()));
        wire.put("username", userProfile.getUsername());
        wire.put("email", userProfile.getEmail());
        wire.put("conversationCount", userProfile.getConversationCount());
        wire.put("favoriteRoleId", userProfile.getFavoriteRoleId() == null
                ? null : userProfile.getFavoriteRoleId().toString());
        wire.put("favoriteRoleName", userProfile.getFavoriteRoleName());
        wire.put("roleUsageCount", userProfile.getRoleUsageCount());
        wire.put("activityLevel", userProfile.getActivityLevel());
        return ResponseEntity.ok(UserProfileProjectionMapper.profile(wire));
    }

    /**
     * 获取个性化推荐
     */
    @GetMapping("/{userId}/recommendations")
    public ResponseEntity<ProfileRecommendationsQuery> getRecommendations(@PathVariable UUID userId) {
        return ResponseEntity.ok(
                UserProfileProjectionMapper.recommendations(userProfileService.getPersonalizedRecommendations(userId)));
    }
}
