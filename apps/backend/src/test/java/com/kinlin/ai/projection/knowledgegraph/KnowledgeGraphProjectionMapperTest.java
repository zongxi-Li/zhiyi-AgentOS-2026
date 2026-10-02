package com.kinlin.ai.projection.knowledgegraph;

import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.projection.knowledgegraph.mapper.KnowledgeGraphProjectionMapper;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Wire contract for the evidenced knowledge-graph queries: the success/data
 * envelope, snake_case stat counters, node/edge order and the dropped unread
 * properties bag.
 */
class KnowledgeGraphProjectionMapperTest {
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private static Set<String> keys(JsonNode node) {
        Set<String> names = new LinkedHashSet<>();
        node.fieldNames().forEachRemaining(names::add);
        return names;
    }

    private static Map<String, Object> row(Object... keyValues) {
        Map<String, Object> result = new java.util.LinkedHashMap<>();
        for (int index = 0; index < keyValues.length; index += 2) {
            result.put(String.valueOf(keyValues[index]), keyValues[index + 1]);
        }
        return result;
    }

    private static JsonNode json(Object mapped) throws Exception {
        return MAPPER.readTree(MAPPER.writeValueAsString(mapped));
    }

    @Test
    void statsEnvelopeKeepsSnakeCaseCounters() throws Exception {
        JsonNode body = json(KnowledgeGraphProjectionMapper.stats(row(
                "entities_count", 12, "relations_count", 30, "triples_count", 25)));
        assertEquals(Set.of("success", "data"), keys(body));
        assertTrue(body.path("success").asBoolean());
        assertEquals(Set.of("entities_count", "relations_count", "triples_count"),
                keys(body.path("data")));
        assertEquals(12, body.path("data").path("entities_count").asLong());
    }

    @Test
    void graphDataKeepsNodeEdgeOrderAndDropsUnreadProperties() throws Exception {
        JsonNode body = json(KnowledgeGraphProjectionMapper.graphData(row(
                "nodes", List.of(
                        row("id", "e1", "label", "合同", "type", "Entity",
                                "properties", Map.of("internal", "drop-me")),
                        row("id", "e2", "label", "条款", "type", "Entity")),
                "edges", List.of(row("from", "e1", "to", "e2", "label", "包含", "arrows", "to")),
                "stats", row("entities_count", 2, "relations_count", 1, "triples_count", 1))));
        JsonNode data = body.path("data");
        assertEquals(Set.of("nodes", "edges", "stats"), keys(data));
        assertEquals(2, data.path("nodes").size());
        assertEquals(Set.of("id", "label", "type"), keys(data.path("nodes").get(0)));
        assertEquals(Set.of("from", "to", "label", "arrows"), keys(data.path("edges").get(0)));
        assertEquals("e1", data.path("nodes").get(0).path("id").asText());
        assertEquals("e2", data.path("nodes").get(1).path("id").asText(), "node order survives");
        assertFalse(MAPPER.writeValueAsString(body).contains("drop-me"));
        assertEquals(2, data.path("stats").path("entities_count").asLong());
    }

    @Test
    void damagedResultsFailLoudlyInsteadOfFakingEmptyGraphs() {
        assertThrows(IllegalArgumentException.class,
                () -> KnowledgeGraphProjectionMapper.stats(Map.of()));
        // An empty graph is a legitimate state; the no-id node row is the break.
        assertThrows(IllegalArgumentException.class, () -> KnowledgeGraphProjectionMapper.graphData(row(
                "nodes", List.of(row("label", "no-id")), "edges", List.of())));
    }
}
