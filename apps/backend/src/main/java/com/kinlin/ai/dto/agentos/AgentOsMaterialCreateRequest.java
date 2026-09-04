package com.kinlin.ai.dto.agentos;

import jakarta.validation.constraints.NotNull;

/** Complete material upload contract; content length is intentionally API-controlled. */
public record AgentOsMaterialCreateRequest(
        @NotNull String content,
        String mediaType
) {
    public AgentOsMaterialCreateRequest {
        mediaType = mediaType == null || mediaType.isBlank() ? "text/plain" : mediaType;
    }
}
