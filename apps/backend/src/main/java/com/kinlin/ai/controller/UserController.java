package com.kinlin.ai.controller;

import com.kinlin.ai.entity.User;
import com.kinlin.ai.projection.user.dto.UserQuery;
import com.kinlin.ai.projection.user.mapper.UserProjectionMapper;
import com.kinlin.ai.security.AuthenticatedUser;
import com.kinlin.ai.service.UserService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.io.Resource;
import org.springframework.core.io.UrlResource;
import org.springframework.http.CacheControl;
import org.springframework.http.MediaType;
import org.springframework.http.MediaTypeFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Locale;
import java.util.Set;
import java.util.UUID;

/**
 * 用户控制器
 */
@RestController
@RequestMapping("/users")
@RequiredArgsConstructor
@Slf4j
public class UserController {

    private final UserService userService;
    private final com.kinlin.ai.service.FileService fileService;
    private static final long MAX_AVATAR_SIZE = 5L * 1024 * 1024;
    private static final Set<String> AVATAR_CONTENT_TYPES = Set.of(
            "image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"
    );

    /**
     * 获取当前用户信息
     */
    @GetMapping("/me")
    public ResponseEntity<UserQuery> getCurrentUser() {
        UUID currentUserId = resolveUserId();
        if (currentUserId == null) {
            return ResponseEntity.badRequest().build();
        }
        return userService.getUserById(currentUserId)
                .map(UserProjectionMapper::toQuery)
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    /**
     * 获取用户信息
     */
    @GetMapping("/{userId}")
    public ResponseEntity<UserQuery> getUser(@PathVariable UUID userId) {
        return userService.getUserById(userId)
                .map(UserProjectionMapper::toQuery)
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    /**
     * 更新用户信息
     */
    @PutMapping("/{userId}")
    public ResponseEntity<UserQuery> updateUser(
            @PathVariable UUID userId,
            @RequestBody User userUpdate
    ) {
        UUID currentUserId = resolveUserId();
        // 验证用户只能更新自己的信息
        if (currentUserId == null || !currentUserId.equals(userId)) {
            return ResponseEntity.badRequest().build();
        }

        return userService.getUserById(userId)
                .map(user -> {
                    // 只更新允许的字段
                    if (userUpdate.getEmail() != null) {
                        user.setEmail(userUpdate.getEmail());
                    }
                    if (userUpdate.getUsername() != null) {
                        user.setUsername(userUpdate.getUsername());
                    }
                    User updated = userService.updateUser(user);
                    return ResponseEntity.ok(UserProjectionMapper.toQuery(updated));
                })
                .orElse(ResponseEntity.notFound().build());
    }

    @PostMapping(value = "/{userId}/avatar", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<UserQuery> uploadAvatar(
            @PathVariable UUID userId,
            @RequestParam("file") MultipartFile file
    ) {
        UUID currentUserId = resolveUserId();
        if (currentUserId == null || !currentUserId.equals(userId)) {
            return ResponseEntity.badRequest().build();
        }
        if (file == null || file.isEmpty()) {
            return ResponseEntity.badRequest().build();
        }
        if (file.getSize() > MAX_AVATAR_SIZE) {
            return ResponseEntity.status(413).build();
        }
        String contentType = file.getContentType();
        if (contentType == null || !AVATAR_CONTENT_TYPES.contains(contentType.toLowerCase(Locale.ROOT))) {
            return ResponseEntity.badRequest().build();
        }

        User user = userService.getUserById(userId).orElse(null);
        if (user == null) {
            return ResponseEntity.notFound().build();
        }

        String previousAvatar = user.getAvatar();
        try {
            String avatarPath = fileService.saveFile(file, "avatars/" + userId);
            user.setAvatar(avatarPath);
            User updated = userService.updateUser(user);
            deletePreviousAvatar(previousAvatar, avatarPath);
            return ResponseEntity.ok(UserProjectionMapper.toQuery(updated));
        } catch (IOException exception) {
            log.error("Avatar upload failed for user {}", userId, exception);
            return ResponseEntity.internalServerError().build();
        }
    }

    @GetMapping("/{userId}/avatar")
    public ResponseEntity<Resource> getAvatar(@PathVariable UUID userId) {
        User user = userService.getUserById(userId).orElse(null);
        if (user == null || user.getAvatar() == null || user.getAvatar().isBlank()) {
            return ResponseEntity.notFound().build();
        }

        try {
            Path avatarPath = fileService.getFilePath(user.getAvatar());
            Resource resource = new UrlResource(avatarPath.toUri());
            if (!resource.exists() || !resource.isReadable() || !Files.isRegularFile(avatarPath)) {
                return ResponseEntity.notFound().build();
            }
            MediaType contentType = MediaTypeFactory.getMediaType(avatarPath.getFileName().toString())
                    .orElse(MediaType.APPLICATION_OCTET_STREAM);
            return ResponseEntity.ok()
                    .contentType(contentType)
                    .cacheControl(CacheControl.noCache())
                    .body(resource);
        } catch (IOException exception) {
            log.warn("Avatar read failed for user {}", userId, exception);
            return ResponseEntity.notFound().build();
        }
    }

    private void deletePreviousAvatar(String previousAvatar, String currentAvatar) {
        if (previousAvatar == null || previousAvatar.isBlank() || previousAvatar.equals(currentAvatar)) {
            return;
        }
        try {
            fileService.deleteFile(previousAvatar);
        } catch (IOException exception) {
            log.warn("Failed to delete previous avatar {}", previousAvatar, exception);
        }
    }

    /**
     * 修改密码
     */
    @PostMapping("/{userId}/password")
    public ResponseEntity<Void> changePassword(
            @PathVariable UUID userId,
            @RequestBody PasswordChangeRequest request
    ) {
        UUID currentUserId = resolveUserId();
        // 验证用户只能修改自己的密码
        if (currentUserId == null || !currentUserId.equals(userId)) {
            return ResponseEntity.badRequest().build();
        }

        // 验证当前密码
        User user = userService.getUserById(userId)
                .orElseThrow(() -> new IllegalArgumentException("用户不存在"));

        if (!userService.validateUser(user.getUsername(), request.getCurrentPassword()).isPresent()) {
            return ResponseEntity.badRequest().build();
        }

        // 更新密码
        userService.updatePassword(userId, request.getNewPassword());
        return ResponseEntity.ok().build();
    }

    /**
     * X-User-Id 请求头已被 SensitiveIdentityHeaderFilter 剥离，一律以认证身份为准。
     */
    private UUID resolveUserId() {
        return AuthenticatedUser.currentUserId().orElse(null);
    }

    /**
     * 密码修改请求DTO
     */
    public static class PasswordChangeRequest {
        private String currentPassword;
        private String newPassword;

        public String getCurrentPassword() {
            return currentPassword;
        }

        public void setCurrentPassword(String currentPassword) {
            this.currentPassword = currentPassword;
        }

        public String getNewPassword() {
            return newPassword;
        }

        public void setNewPassword(String newPassword) {
            this.newPassword = newPassword;
        }
    }
}

