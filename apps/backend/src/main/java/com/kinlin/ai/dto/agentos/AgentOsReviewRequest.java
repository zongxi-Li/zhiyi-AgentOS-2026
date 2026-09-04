package com.kinlin.ai.dto.agentos;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

/** Review command validated at the HTTP boundary and interpreted only by ExecutionRuntime. */
public record AgentOsReviewRequest(
        @NotBlank String stepId,
        @NotBlank @Pattern(regexp = "approved|rejected|need_more_info|rerun|cancelled") String decision,
        String reviewer,
        @Size(max = 2000) String comment,
        @NotBlank String operationId
) {
    public AgentOsReviewRequest {
        reviewer = reviewer == null ? "system" : reviewer;
        comment = comment == null ? "" : comment;
    }
}
