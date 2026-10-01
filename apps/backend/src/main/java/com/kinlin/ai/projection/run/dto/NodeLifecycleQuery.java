package com.kinlin.ai.projection.run.dto;

import java.util.List;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/** Explicit observation fields; never an executable runtime snapshot. */
public record NodeLifecycleQuery(
        String stepId,
        String attemptId,
        String phase,
        String failureCode,
        Integer sequence
) implements QueryResponse { }
