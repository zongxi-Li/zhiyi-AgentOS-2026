package com.kinlin.ai.projection.run.dto;

import java.util.List;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/** Explicit observation fields; never an executable runtime snapshot. */
public record OutputReferenceQuery(
        String stepId,
        String outputRef,
        String summary
) implements QueryResponse { }
