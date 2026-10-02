package com.kinlin.ai.projection.provenance.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

import java.util.List;

/**
 * Typed run provenance response over the agentos_v2.py {@code get_provenance} wire.
 *
 * <p>Two upstream variants: the hash-chained ledger branch ({@code events}, each row
 * an eventType plus a typed payload) and the pre-ledger legacy branch
 * ({@code schemaVersion}/{@code legacy} plus productions/consumptions/interactions
 * rows). Exactly one branch is present per response. The dynamic
 * {@code fieldsByProducer} association becomes typed producer-fields rows on both
 * branches; integrity digests (checksum/previousHash/eventHash) stay public audit
 * facts for the legal/CSV export.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ProvenanceQuery(
        String runId,
        String integrityStatus,
        Long schemaVersion,
        Boolean legacy,
        List<ProvenanceEventQuery> events,
        List<ProvenancePayloadQuery> productions,
        List<ProvenancePayloadQuery> consumptions,
        List<ProvenancePayloadQuery> interactions
) implements QueryResponse {
}
