package com.kinlin.ai.projection.workspace.dto;

import java.util.List;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * Virtual explorer entry (workspace.py WorkspaceEntry). Every explicit upstream field maps
 * verbatim in declaration order; only the free-form {@code metadata} dict is replaced by
 * the typed whitelist {@link WorkspaceEntryMetadataQuery}. {@code content} passes through
 * byte-for-byte for user and Artifact bodies; the single system-generated
 * {@code overview:mission.md} virtual document is rebuilt from public facts by the mapper
 * (registered difference — the upstream document embeds internal mission metadata and
 * plan constraint specs, which must not reach the wire).
 *
 * <p>Entry-level {@code logicalRole} is public identity labeling (task/final-synthesis
 * roles); {@code disposition} and {@code identityQuality} are public enum labels
 * (GENERATED/REUSED, canonical/legacy). Counts and display order are non-negative ints the
 * upstream model already enforces.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record WorkspaceEntryQuery(
        String entryId,
        String kind,
        String name,
        String group,
        String title,
        String parentEntryId,
        int displayOrder,
        String semanticTaskKey,
        String artifactKey,
        String taskId,
        String logicalRole,
        String objective,
        List<String> dependencyKeys,
        int attemptCount,
        String latestAttemptId,
        int artifactCount,
        String artifactId,
        String contentRef,
        String artifactType,
        String mediaType,
        String checksum,
        String attemptId,
        String acgNodeId,
        String disposition,
        String sourceRunId,
        String identityQuality,
        String createdAt,
        String runId,
        String status,
        String blueprintId,
        String graphId,
        Integer graphVersion,
        String parentRunId,
        String completedAt,
        Boolean isActive,
        String content,
        WorkspaceEntryMetadataQuery metadata
) {
    public WorkspaceEntryQuery {
        dependencyKeys = List.copyOf(dependencyKeys);
    }
}
