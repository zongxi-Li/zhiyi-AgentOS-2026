package com.kinlin.ai.projection.history.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

import java.math.BigDecimal;

/**
 * One flat scalar plugin configuration entry. Exactly one scalar slot is set;
 * nested or list values have no approved representation here (both registered
 * plugins emit flat scalars only) and are dropped.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record HistoryPluginEntryQuery(
        String name,
        String text,
        Boolean bool,
        BigDecimal number
) implements QueryResponse {
}
