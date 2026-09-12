package com.kinlin.ai.dto.agentos;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

import java.util.List;
import java.util.Map;

/** Validated transport DTO for creating a successor Run under an existing Mission. */
public record AgentOsMissionRunCreateRequest(
        String workflowId,
        String reviewMode,
        Map<String, Object> input,
        List<String> enabledPluginIds,
        List<String> materialRefs,
        List<String> attachmentIds,
        @NotBlank @Size(max = 200) String clientRequestId,
        @NotBlank String sourceRunId,
        @NotBlank @Size(max = 80) String rerunReason
) {
    public AgentOsMissionRunCreateRequest {
        reviewMode = reviewMode == null ? "auto" : reviewMode;
        input = input == null ? Map.of() : Map.copyOf(input);
        enabledPluginIds = enabledPluginIds == null ? null : List.copyOf(enabledPluginIds);
        materialRefs = materialRefs == null ? null : List.copyOf(materialRefs);
        attachmentIds = attachmentIds == null ? null : List.copyOf(attachmentIds);
    }
}
