package com.kinlin.ai.projection.user.dto;

import java.time.LocalDateTime;
import java.util.UUID;

/** Public user representation; persistence and credential fields are not part of this contract. */
public record UserQuery(
        UUID id,
        String username,
        String email,
        String avatar,
        LocalDateTime createdAt,
        LocalDateTime updatedAt
) { }
