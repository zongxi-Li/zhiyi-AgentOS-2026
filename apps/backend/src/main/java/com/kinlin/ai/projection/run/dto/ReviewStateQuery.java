package com.kinlin.ai.projection.run.dto;

import java.util.List;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/** Explicit observation fields; never an executable runtime snapshot. */
public record ReviewStateQuery(
        String subjectType,
        String subjectId,
        String controlId,
        String stepId,
        String reasonCode,
        Integer iteration,
        Integer approvals,
        Integer quorum,
        Boolean accepted,
        String strategy
) implements QueryResponse { }
