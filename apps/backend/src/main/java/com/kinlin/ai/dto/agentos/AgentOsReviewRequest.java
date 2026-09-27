package com.kinlin.ai.dto.agentos;

import com.fasterxml.jackson.annotation.JsonAnySetter;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

import java.time.Instant;

/** Review command validated at the HTTP boundary and interpreted only by ExecutionRuntime. */
public record AgentOsReviewRequest(
        @NotBlank String stepId,
        @NotBlank @Pattern(regexp = "approved|rejected|need_more_info|rerun|cancelled") String decision,
        String reviewer,
        @Size(max = 2000) String comment,
        @NotBlank String operationId,
        Instant expectedRunUpdatedAt,
        AgentOsStepStatus expectedStepStatus
) {
    public AgentOsReviewRequest(
            String stepId,
            String decision,
            String reviewer,
            String comment,
            String operationId
    ) {
        this(stepId, decision, reviewer, comment, operationId, null, null);
    }

    public AgentOsReviewRequest {
        reviewer = reviewer == null ? "system" : reviewer;
        comment = comment == null ? "" : comment;
    }

    @JsonAnySetter
    public void rejectUnknownField(String name, Object value) {
        throw new IllegalArgumentException("Unsupported review field: " + name);
    }
}
