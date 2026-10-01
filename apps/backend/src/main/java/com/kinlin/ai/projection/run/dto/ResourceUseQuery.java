package com.kinlin.ai.projection.run.dto;

import java.util.List;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/** Explicit observation fields; never an executable runtime snapshot. */
public record ResourceUseQuery(
        String resourceId,
        String agentId,
        String modelId,
        String acgNodeId,
        String deploymentTier
) implements QueryResponse { }
