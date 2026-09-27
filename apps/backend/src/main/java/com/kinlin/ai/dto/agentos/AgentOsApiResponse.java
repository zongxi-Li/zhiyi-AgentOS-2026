package com.kinlin.ai.dto.agentos;

/** Marker for stable AgentOS northbound response bodies. */
public sealed interface AgentOsApiResponse permits
        AgentOsErrorResponse,
        AgentOsMissionResponse,
        AgentOsRunResponse,
        AgentOsReviewResponse,
        AgentOsOperationResponse {
}
