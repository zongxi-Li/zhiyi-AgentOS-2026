package com.kinlin.ai.dto.agentos;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonValue;

public enum AgentOsRunStatus {
    PENDING, PLANNING, RUNNING, RETRYING, WAITING_REVIEW,
    COMPLETED, FAILED, CANCELLED, SUPERSEDED;

    @JsonCreator
    public static AgentOsRunStatus fromJson(String value) {
        return value == null ? null : valueOf(value.trim().toUpperCase());
    }

    @JsonValue
    public String toJson() {
        return name().toLowerCase();
    }
}
