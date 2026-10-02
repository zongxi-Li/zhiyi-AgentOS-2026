package com.kinlin.ai.projection.workspace.dto;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * Mission header inside the Workspace envelope. Mirrors the wave-1 detail/list precedent:
 * {@code userId} and {@code metadata} (identityGeneration/principalSource/runtimeDomain/
 * runtimeIntent — internal control-plane facts) are dropped from the raw Mission model.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record WorkspaceMissionQuery(
        String missionId,
        String goal,
        String description,
        String status,
        String createdAt,
        String updatedAt
) { }
