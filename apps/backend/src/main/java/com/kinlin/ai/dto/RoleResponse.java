package com.kinlin.ai.dto;

import lombok.Data;

import java.time.LocalDateTime;
import java.util.Map;
import java.util.UUID;

/**
 * 角色响应DTO
 */
@Data
public class RoleResponse {

    private UUID id;

    private String name;

    private String description;

    private String roleType;

    private UUID userId;

    private String systemPrompt;

    private Map<String, Object> dialogueStyle;

    private Map<String, Object> personality;

    private Map<String, Object> avatarConfig;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;
}

