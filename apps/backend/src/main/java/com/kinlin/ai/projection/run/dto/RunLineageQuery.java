package com.kinlin.ai.projection.run.dto;

import java.util.List;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/** Explicit observation fields; never an executable runtime snapshot. */
public record RunLineageQuery(
        String parentRunId,
        String sourceRunId,
        String rerunReason,
        String supersedesRunId,
        String supersededByRunId
) implements QueryResponse { }
