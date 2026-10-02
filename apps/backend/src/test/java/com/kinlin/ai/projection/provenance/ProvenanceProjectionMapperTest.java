package com.kinlin.ai.projection.provenance;

import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.projection.provenance.mapper.ProvenanceProjectionMapper;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Wire contract for the provenance projection: the ledger branch (typed events),
 * the legacy branch (typed rows with association rows replacing the dynamic map),
 * branch exclusivity and loud structural failures.
 */
class ProvenanceProjectionMapperTest {
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final String SECRET = "SECRET-PROVENANCE-12345";

    private static Map<String, Object> row(Object... keyValues) {
        Map<String, Object> result = new java.util.LinkedHashMap<>();
        for (int index = 0; index < keyValues.length; index += 2) {
            result.put((String) keyValues[index], keyValues[index + 1]);
        }
        return result;
    }

    @Test
    void ledgerBranchKeepsEventsAndDropsTheLegacyArrays() throws Exception {
        Map<String, Object> wire = Map.of(
                "runId", "run_1",
                "integrityStatus", "valid",
                "events", List.of(
                        row("eventType", "data_produced", "payload", row(
                                "eventId", "prod_1", "producerStepId", "step_1",
                                "fieldNames", List.of("report"), "checksum", "sha:a",
                                "tokenSize", 128, "evidenceRefs", List.of("ev_1"),
                                "eventHash", "hash_1")),
                        row("eventType", "data_consumed", "payload", row(
                                "eventId", "cons_1", "consumerStepId", "step_2",
                                "producerStepIds", List.of("step_1"),
                                "fieldsByProducer", Map.of("step_1", List.of("report", "title", 7)),
                                "consumedFields", List.of("report"),
                                "tokensDelivered", 512, "tokensAvailable", 1024,
                                "savingRatio", 0.5, "contractStatus", "valid",
                                "checksum", "sha:b", "eventHash", "hash_2")),
                        row("eventType", "data_consumed", "payload", row(
                                "eventId", "int_1", "interactionId", "int_1",
                                "producerStepIds", List.of("step_1"), "consumerStepId", "step_2",
                                "fieldsByProducer", Map.of("step_1", List.of("section")),
                                "tokensDelivered", 100, "tokensAvailable", 200,
                                "savingRatio", 0.5, "eventHash", "hash_3"))));
        JsonNode body = json(wire);
        assertEquals(Set.of("runId", "integrityStatus", "events"), keys(body));
        JsonNode consumption = body.path("events").get(1).path("payload");
        assertTrue(consumption.has("producerFields"), "fieldsByProducer must become typed rows");
        assertEquals("step_1", consumption.path("producerFields").get(0).path("producerId").asText());
        assertEquals(2, consumption.path("producerFields").get(0).path("fields").size());
        assertFalse(MAPPER.writeValueAsString(body).contains("fieldsByProducer"));
        // Non-string field entries are filtered, not fatal.
        assertEquals(2, consumption.path("producerFields").get(0).path("fields").size());
        JsonNode interaction = body.path("events").get(2).path("payload");
        assertTrue(interaction.has("interactionId"));
        assertFalse(interaction.has("contractStatus"), "ledger interactions carry no contractStatus");
    }

    @Test
    void legacyBranchKeepsRowsWithSchemaVersionAndAssociationRows() throws Exception {
        Map<String, Object> wire = Map.of(
                "runId", "run_0",
                "schemaVersion", 1,
                "integrityStatus", "unknown",
                "legacy", true,
                "productions", List.of(row(
                        "eventId", "p0", "runId", "run_0", "missionId", "m0", "attempt", 1,
                        "producerStepId", "step_a", "agentName", "agent_a",
                        "checksum", "sha:c", "fieldNames", List.of("brief"),
                        "tokenSize", 64, "evidenceRefs", List.of(),
                        "previousHash", "", "eventHash", "hash_0",
                        "createdAt", "2026-09-01T00:00:00Z")),
                "consumptions", List.of(row(
                        "eventId", "c0", "consumerStepId", "step_b",
                        "producerStepIds", List.of("step_a"),
                        "fieldsByProducer", Map.of("step_a", List.of("brief")),
                        "consumedFields", List.of("brief"),
                        "tokensDelivered", 10, "tokensAvailable", 20, "savingRatio", 0.5,
                        "contractStatus", "valid", "checksum", "sha:d")),
                "interactions", List.of(row(
                        "eventId", "i0", "interactionId", "i0", "edgeIds", List.of("e1"),
                        "producerStepIds", List.of("step_a"), "consumerStepId", "step_b",
                        "producerAgentNames", List.of("agent_a"), "consumerAgentName", "agent_b",
                        "fieldsByProducer", Map.of("step_a", List.of("brief")),
                        "tokensDelivered", 10, "tokensAvailable", 20, "savingRatio", 0.5,
                        "evidenceRefs", List.of(), "contractStatus", "valid",
                        "internalState", SECRET)));
        JsonNode body = json(wire);
        assertEquals(Set.of("runId", "integrityStatus", "schemaVersion", "legacy",
                "productions", "consumptions", "interactions"), keys(body));
        assertTrue(body.path("legacy").asBoolean());
        assertEquals(1, body.path("schemaVersion").asLong());
        JsonNode interaction = body.path("interactions").get(0);
        assertTrue(interaction.has("producerFields"));
        assertFalse(MAPPER.writeValueAsString(body).contains("fieldsByProducer"));
        assertFalse(MAPPER.writeValueAsString(body).contains(SECRET));
    }

    @Test
    void malformedRowsFailLoudlyAndBranchesStayExclusive() {
        // Unknown branch: no events, no legacy arrays.
        assertThrows(IllegalArgumentException.class, () -> mapper(Map.of(
                "runId", "run_1", "integrityStatus", "valid")));
        // Ledger branch with a null events list.
        Map<String, Object> nullEvents = new java.util.LinkedHashMap<>();
        nullEvents.put("runId", "run_1");
        nullEvents.put("integrityStatus", "valid");
        nullEvents.put("events", null);
        assertThrows(IllegalArgumentException.class, () -> mapper(nullEvents));
        // Event row without a payload object.
        assertThrows(IllegalArgumentException.class, () -> mapper(Map.of(
                "runId", "run_1", "integrityStatus", "valid",
                "events", List.of(row("eventType", "data_produced")))));
        // Legacy branch missing one of the three arrays.
        assertThrows(IllegalArgumentException.class, () -> mapper(Map.of(
                "runId", "run_1", "integrityStatus", "unknown",
                "productions", List.of(), "consumptions", List.of())));
        // A fieldsByProducer that is not a map is a contract break, not silent data loss.
        assertThrows(IllegalArgumentException.class, () -> mapper(Map.of(
                "runId", "run_1", "integrityStatus", "valid",
                "events", List.of(row("eventType", "data_consumed", "payload", row(
                        "eventId", "c", "consumerStepId", "s", "fieldsByProducer", "broken"))))));
    }

    private static JsonNode json(Map<String, Object> wire) throws Exception {
        return MAPPER.readTree(MAPPER.writeValueAsString(ProvenanceProjectionMapper.provenance(wire)));
    }

    private static Object mapper(Map<String, Object> wire) {
        return ProvenanceProjectionMapper.provenance(wire);
    }

    private static Set<String> keys(JsonNode node) {
        Set<String> names = new LinkedHashSet<>();
        node.fieldNames().forEachRemaining(names::add);
        return names;
    }
}
