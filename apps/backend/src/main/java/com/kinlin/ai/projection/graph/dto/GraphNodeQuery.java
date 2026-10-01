package com.kinlin.ai.projection.graph.dto;

import java.util.List;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/** Explicit observation fields; never an executable runtime snapshot. */
public record GraphNodeQuery(
        String nodeId,
        String nodeType,
        String name,
        String description,
        String goal,
        String agentName,
        String capability,
        String controlType,
        GraphDisplayQuery display
) implements QueryResponse { }
