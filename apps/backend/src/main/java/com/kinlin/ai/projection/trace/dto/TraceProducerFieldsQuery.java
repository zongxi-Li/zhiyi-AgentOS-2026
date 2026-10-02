package com.kinlin.ai.projection.trace.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

import java.util.List;

/**
 * Typed association row replacing the upstream dynamic {@code fieldsByProducer}
 * map: which producer step delivered which fields to the consumer. The producer
 * identity is data, not a wire key, so no Map field is needed.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record TraceProducerFieldsQuery(
        String producerId,
        List<String> fields
) implements QueryResponse {
}
