package com.kinlin.ai.projection.workspace.dto;

import java.util.List;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * Navigation row of the envelope-level {@code graphNodes} list (workspace.py
 * WorkspaceGraphNode). This is a different structure from the graph node DTO: it joins
 * the blueprint node to its SemanticTask identity and this Run's attempt/artifact facts
 * for the run-progress navigator. All eleven fields map verbatim; {@code status} is the
 * latest attempt's public status label.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record WorkspaceGraphNodeQuery(
        String acgNodeId,
        String nodeType,
        String name,
        String semanticTaskKey,
        String taskId,
        String identityQuality,
        int displayOrder,
        String status,
        String attemptId,
        int artifactCount,
        List<String> artifactIds
) {
    public WorkspaceGraphNodeQuery {
        artifactIds = List.copyOf(artifactIds);
    }
}
