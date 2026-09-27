package com.kinlin.ai.dto.agentos;

import com.fasterxml.jackson.annotation.JsonAnySetter;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

import java.util.List;
import java.util.Map;

/** Validated transport DTO; workflow state remains owned by Python. */
public record AgentOsMissionCreateRequest(
        @NotBlank @Size(max = 500) String title,
        String domain,
        String intent,
        String workflowId,
        String reviewMode,
        Map<String, Object> input,
        String securityLevel,
        String priority,
        List<String> enabledPluginIds,
        List<String> materialRefs,
        List<String> attachmentIds,
        @Size(max = 200) String clientRequestId
) {
    public AgentOsMissionCreateRequest {
        domain = domain == null ? "general" : domain;
        intent = intent == null ? "general" : intent;
        reviewMode = reviewMode == null ? "auto" : reviewMode;
        input = input == null ? Map.of() : Map.copyOf(input);
        securityLevel = securityLevel == null ? "internal" : securityLevel;
        priority = priority == null ? "normal" : priority;
        enabledPluginIds = enabledPluginIds == null ? null : List.copyOf(enabledPluginIds);
        materialRefs = materialRefs == null ? null : List.copyOf(materialRefs);
        attachmentIds = attachmentIds == null ? null : List.copyOf(attachmentIds);
    }

    @JsonAnySetter
    public void rejectUnknownField(String name, Object value) {
        throw new IllegalArgumentException("Unsupported mission field: " + name);
    }
}
