package com.kinlin.ai.projection.recovery;

import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.projection.identity.dto.IdentityHealthQuery;
import com.kinlin.ai.projection.identity.mapper.IdentityProjectionMapper;
import com.kinlin.ai.projection.recovery.mapper.RecoveryProjectionMapper;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Wire contracts for the recovery-availability and identity-health projections:
 * real canResume/version facts, no checkpoint internals, the full public health
 * counter set, and loud structural failures.
 */
class RecoveryAndIdentityProjectionMapperTest {
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private static Set<String> keys(JsonNode node) {
        Set<String> names = new LinkedHashSet<>();
        node.fieldNames().forEachRemaining(names::add);
        return names;
    }

    @Test
    void checkpointsKeepPublicAvailabilityFactsOnly() throws Exception {
        JsonNode body = json(RecoveryProjectionMapper.checkpoints(Map.of(
                "runId", "run_1",
                "items", List.of(Map.of("checkpointId", "ckpt_1", "version", 3, "canResume", true)),
                "total", 1)));
        assertEquals(Set.of("runId", "items", "total"), keys(body));
        JsonNode row = body.path("items").get(0);
        assertEquals(Set.of("checkpointId", "version", "canResume"), keys(row));
        assertTrue(row.path("canResume").asBoolean());
        assertEquals(3, row.path("version").asLong());
    }

    @Test
    void emptyCheckpointListIsAHonestNoCheckpointState() throws Exception {
        JsonNode body = json(RecoveryProjectionMapper.checkpoints(Map.of(
                "runId", "run_1", "items", List.of(), "total", 0)));
        assertEquals(0, body.path("items").size());
        assertEquals(0, body.path("total").asLong());
    }

    @Test
    void damagedCheckpointRowsFailInsteadOfFakingAvailability() {
        assertThrows(IllegalArgumentException.class, () -> RecoveryProjectionMapper.checkpoints(Map.of(
                "runId", "run_1", "total", 0)));
        assertThrows(IllegalArgumentException.class, () -> RecoveryProjectionMapper.checkpoints(Map.of(
                "runId", "run_1", "items", List.of(Map.of("checkpointId", "c", "version", 1)), "total", 1)));
        assertThrows(IllegalArgumentException.class, () -> RecoveryProjectionMapper.checkpoints(Map.of(
                "runId", "run_1",
                "items", List.of(Map.of("checkpointId", "c", "version", -1, "canResume", true)),
                "total", 1)));
    }

    @Test
    void identityHealthKeepsTheFullPublicCounterSet() throws Exception {
        Map<String, Object> wire = new java.util.LinkedHashMap<>(Map.of(
                "status", "degraded", "source", "agentos-v2",
                "backlogCount", 2, "failedCount", 1,
                "unappliedEventCount", 2, "inboxBacklog", 0, "outboxBacklog", 0,
                "startupReconciliation", Map.of("examinedMissions", 1, "examinedRuns", 2,
                        "repairedMissions", 0, "repairedRuns", 1, "replayedEvents", 3,
                        "failureCount", 0)));
        JsonNode body = json(IdentityProjectionMapper.identityHealth(wire));
        assertEquals(Set.of("status", "source", "backlogCount", "failedCount", "unappliedEventCount",
                "inboxBacklog", "outboxBacklog", "startupReconciliation"), keys(body));
        assertEquals("degraded", body.path("status").asText());
        assertEquals(Set.of("examinedMissions", "examinedRuns", "repairedMissions",
                "repairedRuns", "replayedEvents", "failureCount"), keys(body.path("startupReconciliation")));
        assertEquals(3, body.path("startupReconciliation").path("replayedEvents").asLong());
        assertFalse(body.has("oldestEventAt"), "a null oldestEventAt stays absent, not fake");
        assertFalse(MAPPER.writeValueAsString(body).contains("repository"));
    }

    @Test
    void damagedHealthEnvelopesFailLoudly() {
        assertThrows(IllegalArgumentException.class, () -> IdentityProjectionMapper.identityHealth(Map.of(
                "status", "healthy", "source", "agentos-v2")));
        assertThrows(IllegalArgumentException.class, () -> IdentityProjectionMapper.identityHealth(Map.of(
                "status", "healthy", "source", "agentos-v2", "backlogCount", 0, "failedCount", 0,
                "unappliedEventCount", 0, "inboxBacklog", 0, "outboxBacklog", 0,
                "startupReconciliation", Map.of())));
        assertThrows(IllegalArgumentException.class, () -> IdentityProjectionMapper.identityHealth(Map.of(
                "status", "healthy", "source", "agentos-v2", "backlogCount", -1, "failedCount", 0,
                "unappliedEventCount", 0, "inboxBacklog", 0, "outboxBacklog", 0,
                "startupReconciliation", Map.of("examinedMissions", 0, "examinedRuns", 0,
                        "repairedMissions", 0, "repairedRuns", 0, "replayedEvents", 0, "failureCount", 0))));
    }

    private static JsonNode json(Object mapped) throws Exception {
        return MAPPER.readTree(MAPPER.writeValueAsString(mapped));
    }
}
