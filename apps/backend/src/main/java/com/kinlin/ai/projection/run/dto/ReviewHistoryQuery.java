package com.kinlin.ai.projection.run.dto;

import java.util.List;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/** Explicit observation fields; never an executable runtime snapshot. */
public record ReviewHistoryQuery(
        String runId,
        List<ReviewItemQuery> items,
        Long total
) implements QueryResponse {
    public ReviewHistoryQuery {
        items = List.copyOf(items);
    }
 }
