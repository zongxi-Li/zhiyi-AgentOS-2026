package com.kinlin.ai.projection.message.dto;

import java.time.LocalDateTime;
import java.util.UUID;

/** Public chat message representation; content and fileUrl behavior match the legacy entity response. */
public record MessageQuery(
        UUID id,
        UUID conversationId,
        MessageRoleQuery role,
        String content,
        MessageTypeQuery messageType,
        String fileUrl,
        MessageMetadataQuery metadata,
        LocalDateTime createdAt
) { }
