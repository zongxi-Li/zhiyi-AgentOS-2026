package com.kinlin.ai.projection.graph.dto;

import java.util.List;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/** Explicit observation fields; never an executable runtime snapshot. */
public record GraphQuery(
        String runId,
        String graphId,
        Integer graphVersion,
        String missionId,
        String objective,
        String complexityLevel,
        List<GraphNodeQuery> nodes,
        List<GraphEdgeQuery> edges,
        List<String> completedStepIds,
        List<String> activeStepIds,
        List<String> skippedStepIds
) implements QueryResponse {
    public GraphQuery {
        nodes = List.copyOf(nodes);
        edges = List.copyOf(edges);
        completedStepIds = List.copyOf(completedStepIds);
        activeStepIds = List.copyOf(activeStepIds);
        skippedStepIds = List.copyOf(skippedStepIds);
    }
 }
