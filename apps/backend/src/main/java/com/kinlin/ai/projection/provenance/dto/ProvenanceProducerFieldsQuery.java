package com.kinlin.ai.projection.provenance.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

import java.util.List;

/**
 * Typed association row replacing the upstream dynamic {@code fieldsByProducer}
 * map: which producer step delivered which fields to the consumer.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ProvenanceProducerFieldsQuery(
        String producerId,
        List<String> fields
) implements QueryResponse {
}
