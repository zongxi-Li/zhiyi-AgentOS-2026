package com.kinlin.ai.projection.output.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/**
 * One named member of an object-shaped content value; the name is data, not a wire
 * key, so no Map field is needed and arbitrary key names survive unchanged.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ContentMemberQuery(
        String name,
        ContentValueQuery value
) implements QueryResponse {
}
