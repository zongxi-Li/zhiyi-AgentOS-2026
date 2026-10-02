package com.kinlin.ai.projection.provenance.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

import java.util.List;

/**
 * The whitelisted public fields shared by provenance productions, consumptions and
 * interactions on both the ledger and the legacy branch. Nullable groups fill in
 * per variant; the producer→fields association is typed rows, never a raw map.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ProvenancePayloadQuery(
        String eventId,
        String runId,
        String missionId,
        Integer attempt,
        String producerStepId,
        String agentName,
        List<String> fieldNames,
        Long tokenSize,
        List<String> evidenceRefs,
        String checksum,
        String previousHash,
        String eventHash,
        String createdAt,
        String consumerStepId,
        String consumerAgentName,
        List<String> producerStepIds,
        List<String> producerEventIds,
        List<String> consumedFields,
        List<ProvenanceProducerFieldsQuery> producerFields,
        Long tokensDelivered,
        Long tokensAvailable,
        Double savingRatio,
        String contractStatus,
        String interactionId,
        List<String> edgeIds,
        List<String> producerAgentNames
) implements QueryResponse {
}
