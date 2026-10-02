package com.kinlin.ai.projection.memory;

import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.projection.memory.mapper.MemoryEventsProjectionMapper;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Wire contract for the polled memory-events projection: the three row variants,
 * dropped unconsumed fields, the [redacted] capsule tokenCount text type, polling
 * tolerance for malformed rows and loud envelope failures.
 */
class MemoryEventsProjectionMapperTest {
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final String SECRET = "SECRET-MEMORY-12345";

    private static Map<String, Object> envelope(List<Map<String, Object>> items) {
        return Map.of("runId", "run_1", "items", items, "total", items.size());
    }

    private static Map<String, Object> row(Object... keyValues) {
        Map<String, Object> result = new java.util.LinkedHashMap<>();
        for (int index = 0; index < keyValues.length; index += 2) {
            result.put((String) keyValues[index], keyValues[index + 1]);
        }
        return result;
    }

    @Test
    void accessRowKeepsReaderFieldsAndDropsUnreadBudget() throws Exception {
        Map<String, Object> wire = envelope(List.of(Map.of(
                "kind", "memory_access", "stepId", "step_1", "retrievalMode", "hybrid",
                "hitRefs", List.of("memory:run_1:step_0", 42), "budget", 4096,
                "fallbackReason", "no vector store", "createdAt", "2026-10-02T10:00:00Z")));
        JsonNode row = json(wire).path("items").get(0);
        assertEquals(Set.of("kind", "stepId", "createdAt", "retrievalMode", "hitRefs",
                "fallbackReason"), keys(row));
        assertEquals("hybrid", row.path("retrievalMode").asText());
        assertEquals(1, row.path("hitRefs").size(), "non-string refs are filtered, not fatal");
        assertFalse(row.has("budget"), "budget has no frontend reader and is dropped");
    }

    @Test
    void memoryEventRowKeepsSummaryMetricsAndDropsInternalReferences() throws Exception {
        Map<String, Object> wire = envelope(List.of(row(
                "kind", "memory_event", "eventId", "mem_1", "runId", "run_1", "stepId", "step_2",
                "commitId", "commit_9", "summary", "结构化记忆事件", "decision", "write",
                "relations", List.of(Map.of("sourceStepId", "step_1", "targetStepId", "step_2")),
                "evidenceRefs", List.of("ev_1"),
                "metrics", Map.of("fieldCount", 3, "evidenceCount", 1, "toolCallCount", 2,
                        "modelInvocationCount", 1, "unknownMetric", 99),
                "createdAt", "2026-10-02T10:01:00Z")));
        JsonNode row = json(wire).path("items").get(0);
        assertEquals(Set.of("kind", "stepId", "createdAt", "summary", "metrics"), keys(row));
        assertEquals(Set.of("fieldCount", "evidenceCount", "modelInvocationCount", "toolCallCount"),
                keys(row.path("metrics")));
        assertFalse(MAPPER.writeValueAsString(row).contains("commit_9"));
        assertFalse(MAPPER.writeValueAsString(row).contains("relations"));
    }

    @Test
    void capsuleTokenCountStaysTheHonestRedactedText() throws Exception {
        Map<String, Object> wire = envelope(List.of(Map.of(
                "kind", "phase_capsule", "phaseId", "phase_1", "capsuleRef", "cap_1",
                "sourceMemoryRefs", List.of("memory:run_1:step_1"),
                "evidenceRefs", List.of("ev_2"), "tokenCount", "[redacted]")));
        JsonNode row = json(wire).path("items").get(0);
        assertEquals(Set.of("kind", "phaseId", "sourceMemoryRefs", "tokenCount"), keys(row));
        assertTrue(row.path("tokenCount").isTextual(), "upstream marks tokenCount as [redacted] text");
        assertEquals("[redacted]", row.path("tokenCount").asText());
        assertFalse(row.has("capsuleRef"));
        assertFalse(row.has("evidenceRefs"));
    }

    @Test
    void unknownRowKindKeepsOnlyCommonFieldsWithoutFailingThePoll() throws Exception {
        Map<String, Object> wire = envelope(List.of(Map.of(
                "kind", "memory_future_kind", "stepId", "step_3",
                "internalState", SECRET)));
        JsonNode row = json(wire).path("items").get(0);
        assertEquals("memory_future_kind", row.path("kind").asText());
        assertEquals("step_3", row.path("stepId").asText());
        assertFalse(MAPPER.writeValueAsString(row).contains(SECRET));
    }

    @Test
    void brokenEnvelopeFailsLoudlyInsteadOfEmptyingTheMemoryView() {
        assertThrows(IllegalArgumentException.class,
                () -> MemoryEventsProjectionMapper.memoryEvents(Map.of("runId", "run_1", "total", 0)));
        assertThrows(IllegalArgumentException.class, () -> MemoryEventsProjectionMapper.memoryEvents(Map.of(
                "runId", "run_1", "items", List.of())));
        assertThrows(IllegalArgumentException.class, () -> MemoryEventsProjectionMapper.memoryEvents(Map.of(
                "runId", "run_1", "items", List.of(), "total", -1)));
        assertThrows(IllegalArgumentException.class, () -> MemoryEventsProjectionMapper.memoryEvents(Map.of(
                "items", List.of(), "total", 0)));
    }

    @Test
    void serializedEnvelopeIsExactlyRunIdItemsTotal() throws Exception {
        JsonNode body = json(envelope(List.of(Map.of("kind", "memory_access", "stepId", "s"))));
        assertEquals(Set.of("runId", "items", "total"), keys(body));
        assertEquals("run_1", body.path("runId").asText());
        assertEquals(1, body.path("total").asLong());
    }

    private static JsonNode json(Map<String, Object> wire) throws Exception {
        return MAPPER.readTree(MAPPER.writeValueAsString(MemoryEventsProjectionMapper.memoryEvents(wire)));
    }

    private static Set<String> keys(JsonNode node) {
        Set<String> names = new LinkedHashSet<>();
        node.fieldNames().forEachRemaining(names::add);
        return names;
    }
}
