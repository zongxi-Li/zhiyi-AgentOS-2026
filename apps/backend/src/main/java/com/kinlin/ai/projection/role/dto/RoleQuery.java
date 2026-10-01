package com.kinlin.ai.projection.role.dto;

import java.time.LocalDateTime;
import java.util.UUID;

public record RoleQuery(
        UUID id,
        String name,
        String description,
        RoleKind roleType,
        UUID userId,
        String stableKey,
        String systemPrompt,
        RoleConfigurationQuery dialogueStyle,
        RoleConfigurationQuery personality,
        RoleConfigurationQuery avatarConfig,
        LocalDateTime createdAt,
        LocalDateTime updatedAt
) { }
