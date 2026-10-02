package com.kinlin.ai.projection.output.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/**
 * One legacy outputs row: step identity fields plus the full product body in the
 * content value grammar.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record LegacyOutputItemQuery(
        String stepId,
        String name,
        String status,
        ContentValueQuery content
) implements QueryResponse {
}
