package com.kinlin.ai.dto;

import lombok.Data;

import java.time.LocalDateTime;
import java.util.Map;
import java.util.UUID;

/**
 * 消息响应DTO
 */
@Data
public class MessageResponse {

    private UUID id;

    private UUID conversationId;

    private String role;

    private String content;

    private String messageType;

    private Map<String, Object> metadata;

    private LocalDateTime createdAt;
}

