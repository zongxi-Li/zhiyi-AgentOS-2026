package com.kinlin.ai.dto.agentos;

public record AgentOsErrorResponse(
        String code,
        String message,
        String requestId
) implements AgentOsApiResponse {
}
