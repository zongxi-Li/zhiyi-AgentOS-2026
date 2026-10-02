package com.kinlin.ai.projection.resource.dto;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * Public composition counters, completion state and task progress. Counts are exact
 * non-negative integers; {@code taskProgress} is the upstream finite ratio or absent
 * before any task exists.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record CompositionQuery(
        int materialManifestCount,
        int materialFragmentCount,
        int taskCount,
        int completedTaskCount,
        int persistedResultFragmentCount,
        int reducerManifestCount,
        int chapterCount,
        int artifactCount,
        boolean assemblyComplete,
        Double taskProgress
) {
}
