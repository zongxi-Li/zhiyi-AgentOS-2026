package com.kinlin.ai.projection.role.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

/** Retains the context route's existing snake_case wire names. */
public record RoleContextQuery(
        @JsonProperty("role_id") String roleId,
        String name,
        String description,
        RoleConfigurationQuery personality,
        @JsonProperty("system_prompt") String systemPrompt,
        @JsonProperty("dialogue_style") RoleConfigurationQuery dialogueStyle
) { }
