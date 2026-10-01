package com.kinlin.ai.projection.graph.dto;

import java.util.List;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/** Explicit observation fields; never an executable runtime snapshot. */
public record GraphDisplayQuery(
        String semanticTaskKey,
        String taskId,
        String logicalRole,
        String endpointRole,
        String agentName,
        List<String> allowedSkills,
        List<String> dependencyKeys,
        Integer displayOrder
) implements QueryResponse {
    public GraphDisplayQuery {
        allowedSkills = List.copyOf(allowedSkills);
        dependencyKeys = List.copyOf(dependencyKeys);
    }
 }
