package com.kinlin.ai.dto.agentos;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonValue;

public enum AgentOsLifecyclePhase {
    UNDERSTANDING, PLANNING, GRAPH_BUILDING, EXECUTING, RECOVERY,
    REVIEW, COMPLETED, FAILED, CANCELLED;

    @JsonCreator
    public static AgentOsLifecyclePhase fromJson(String value) {
        return value == null ? null : valueOf(value.trim().toUpperCase());
    }

    @JsonValue
    public String toJson() {
        return name().toLowerCase();
    }
}
