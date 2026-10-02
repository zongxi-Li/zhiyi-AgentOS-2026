package com.kinlin.ai.projection.graph.dto;

import java.util.List;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/** Explicit observation fields; never an executable runtime snapshot. */
public record GraphEdgeQuery(
        String edgeId,
        String sourceId,
        String targetId,
        String edgeType,
        String activation,
        GraphDisplayQuery display
) implements QueryResponse { }
