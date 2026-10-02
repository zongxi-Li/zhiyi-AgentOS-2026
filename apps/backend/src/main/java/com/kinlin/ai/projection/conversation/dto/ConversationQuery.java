package com.kinlin.ai.projection.conversation.dto;

import java.time.LocalDateTime;
import java.util.UUID;

/** Public conversation representation; only owner-visible fields, same JSON shape as the legacy entity response. */
public record ConversationQuery(
        UUID id,
        UUID userId,
        UUID roleId,
        String contextId,
        String title,
        String workspaceMode,
        String preview,
        LocalDateTime createdAt,
        LocalDateTime updatedAt
) { }
