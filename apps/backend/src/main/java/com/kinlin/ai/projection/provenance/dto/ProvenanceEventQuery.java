package com.kinlin.ai.projection.provenance.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/**
 * One ledger provenance row: the upstream eventType plus its whitelisted public
 * payload. The payload variant follows the upstream shape predicates the frontend
 * filters on (producerStepId without consumerStepId → production, interactionId →
 * interaction, otherwise consumption).
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ProvenanceEventQuery(
        String eventType,
        ProvenancePayloadQuery payload
) implements QueryResponse {
}
