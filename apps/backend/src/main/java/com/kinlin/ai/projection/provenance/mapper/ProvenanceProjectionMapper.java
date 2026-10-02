package com.kinlin.ai.projection.provenance.mapper;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import com.kinlin.ai.projection.common.mapper.QueryWire;
import com.kinlin.ai.projection.provenance.dto.ProvenanceEventQuery;
import com.kinlin.ai.projection.provenance.dto.ProvenancePayloadQuery;
import com.kinlin.ai.projection.provenance.dto.ProvenanceProducerFieldsQuery;
import com.kinlin.ai.projection.provenance.dto.ProvenanceQuery;

import static com.kinlin.ai.projection.common.mapper.QueryWire.decimal;
import static com.kinlin.ai.projection.common.mapper.QueryWire.invalid;
import static com.kinlin.ai.projection.common.mapper.QueryWire.items;
import static com.kinlin.ai.projection.common.mapper.QueryWire.object;
import static com.kinlin.ai.projection.common.mapper.QueryWire.requiredText;
import static com.kinlin.ai.projection.common.mapper.QueryWire.smallInt;
import static com.kinlin.ai.projection.common.mapper.QueryWire.text;

/**
 * Pure whitelist mapping from the agentos_v2.py {@code get_provenance} wire to typed
 * provenance DTOs. No I/O, no state, no recomputation: integrity status, hash-chain
 * digests and delivery counters pass through untouched, and the dynamic
 * {@code fieldsByProducer} map becomes typed producer-fields rows on both the
 * ledger and the legacy branch (rows with non-string field entries are filtered).
 */
public final class ProvenanceProjectionMapper {
    private ProvenanceProjectionMapper() {
    }

    public static ProvenanceQuery provenance(Map<String, Object> wire) {
        String runId = requiredText(wire, "runId");
        String integrityStatus = requiredText(wire, "integrityStatus");
        if (wire.containsKey("events")) {
            if (wire.get("events") == null) {
                throw invalid();
            }
            return new ProvenanceQuery(runId, integrityStatus, null, null,
                    items(wire.get("events"), ProvenanceProjectionMapper::event),
                    null, null, null);
        }
        if (wire.get("productions") == null || wire.get("consumptions") == null
                || wire.get("interactions") == null) {
            throw invalid();
        }
        return new ProvenanceQuery(runId, integrityStatus,
                QueryWire.integer(wire, "schemaVersion"), legacyFlag(wire),
                null,
                items(wire.get("productions"), ProvenanceProjectionMapper::payload),
                items(wire.get("consumptions"), ProvenanceProjectionMapper::payload),
                items(wire.get("interactions"), ProvenanceProjectionMapper::payload));
    }

    private static Boolean legacyFlag(Map<String, Object> wire) {
        Boolean legacy = QueryWire.bool(wire, "legacy");
        return legacy != null && legacy;
    }

    private static ProvenanceEventQuery event(Map<?, ?> raw) {
        if (raw.get("payload") == null) {
            throw invalid();
        }
        return new ProvenanceEventQuery(
                requiredText(raw, "eventType"),
                payload(object(raw.get("payload"))));
    }

    private static ProvenancePayloadQuery payload(Map<?, ?> raw) {
        return new ProvenancePayloadQuery(
                text(raw, "eventId"),
                text(raw, "runId"),
                text(raw, "missionId"),
                smallInt(raw, "attempt"),
                text(raw, "producerStepId"),
                text(raw, "agentName"),
                QueryWire.texts(raw.get("fieldNames")),
                QueryWire.integer(raw, "tokenSize"),
                QueryWire.texts(raw.get("evidenceRefs")),
                text(raw, "checksum"),
                text(raw, "previousHash"),
                text(raw, "eventHash"),
                text(raw, "createdAt"),
                text(raw, "consumerStepId"),
                text(raw, "consumerAgentName"),
                QueryWire.texts(raw.get("producerStepIds")),
                QueryWire.texts(raw.get("producerEventIds")),
                QueryWire.texts(raw.get("consumedFields")),
                producerFields(raw.get("fieldsByProducer")),
                QueryWire.integer(raw, "tokensDelivered"),
                QueryWire.integer(raw, "tokensAvailable"),
                decimal(raw, "savingRatio"),
                text(raw, "contractStatus"),
                text(raw, "interactionId"),
                QueryWire.texts(raw.get("edgeIds")),
                QueryWire.texts(raw.get("producerAgentNames")));
    }

    private static List<ProvenanceProducerFieldsQuery> producerFields(Object raw) {
        if (raw == null) {
            return null;
        }
        if (!(raw instanceof Map<?, ?> map)) {
            throw invalid();
        }
        List<ProvenanceProducerFieldsQuery> rows = new ArrayList<>();
        for (Map.Entry<?, ?> entry : map.entrySet()) {
            if (!(entry.getKey() instanceof String producerId) || producerId.isBlank()) {
                continue;
            }
            List<String> fields = safeStrings(entry.getValue());
            if (!fields.isEmpty()) {
                rows.add(new ProvenanceProducerFieldsQuery(producerId, fields));
            }
        }
        return rows.isEmpty() ? null : rows;
    }

    private static List<String> safeStrings(Object raw) {
        if (!(raw instanceof List<?> list)) {
            return List.of();
        }
        List<String> result = new ArrayList<>();
        for (Object item : list) {
            if (item instanceof String value) {
                result.add(value);
            }
        }
        return result;
    }
}
