package com.kinlin.ai.projection.history.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

import java.util.List;

/**
 * One plugin's flat scalar configuration block, identified by data (pluginId),
 * never by a wire map.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record HistoryPluginDataQuery(
        String pluginId,
        List<HistoryPluginEntryQuery> entries
) implements QueryResponse {
}
