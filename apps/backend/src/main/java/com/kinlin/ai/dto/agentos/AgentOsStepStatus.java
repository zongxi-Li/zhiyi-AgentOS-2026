package com.kinlin.ai.dto.agentos;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonValue;

public enum AgentOsStepStatus {
    PENDING, READY, RUNNING, RETRYING, WAITING_REVIEW,
    COMPLETED, FAILED, SKIPPED, CANCELLED;

    @JsonCreator
    public static AgentOsStepStatus fromJson(String value) {
        return value == null ? null : valueOf(value.trim().toUpperCase());
    }

    @JsonValue
    public String toJson() {
        return name().toLowerCase();
    }
}
