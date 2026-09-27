package com.kinlin.ai.dto.agentos;

import com.fasterxml.jackson.annotation.JsonAnySetter;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.PositiveOrZero;
import jakarta.validation.constraints.Size;
import jakarta.validation.constraints.NotBlank;

/** Runtime-only retry command. No semantic patch or concrete resource override is accepted. */
public record AgentOsRetryRequest(
        @NotBlank @Size(max = 200) String clientRequestId,
        @Size(max = 500) String reason,
        @PositiveOrZero Long expectedRuntimeRevision,
        @Pattern(regexp = "successor_run|current_run") String mode
) {
    public AgentOsRetryRequest {
        reason = reason == null || reason.isBlank() ? "operator_requested" : reason;
        mode = mode == null || mode.isBlank() ? "successor_run" : mode;
    }

    @JsonAnySetter
    public void rejectUnknownField(String name, Object value) {
        throw new IllegalArgumentException("Unsupported retry field: " + name);
    }
}
