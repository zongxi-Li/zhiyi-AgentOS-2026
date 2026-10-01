package com.kinlin.ai.projection.run.dto;

import java.util.List;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/** Explicit observation fields; never an executable runtime snapshot. */
public record RunPageQuery(
        List<RunQuery> items,
        Long total,
        Integer page,
        Integer pageSize
) implements QueryResponse {
    public RunPageQuery {
        items = List.copyOf(items);
    }
 }
