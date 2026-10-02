package com.kinlin.ai.projection.output;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.projection.output.mapper.OutputProjectionMapper;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Content value grammar contract for the output bodies: complete preservation of
 * scalars, order, booleans, nulls and exact numbers; loud failure on grammar
 * violations; the legacy-outputs envelope shape.
 */
class OutputProjectionMapperTest {
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private static Map<String, Object> row(Object... keyValues) {
        Map<String, Object> result = new LinkedHashMap<>();
        for (int index = 0; index < keyValues.length; index += 2) {
            result.put((String) keyValues[index], keyValues[index + 1]);
        }
        return result;
    }

    @Test
    void scalarKindsRoundTripCompletely() throws Exception {
        JsonNode content = json(OutputProjectionMapper.output(row(
                "runId", "run_1", "outputRef", "out_1",
                "content", row(
                        "report_markdown", "# 报告\n很长的正文".repeat(500),
                        "final_answer", null,
                        "riskParallel", true,
                        "score", 0.1,
                        "bigTotal", 3_000_000_000L,
                        "negative", -7,
                        "artifacts", List.of(
                                row("artifactId", "a1", "content", "正文"),
                                List.of(1, 2)),
                        "emptyObject", Map.of()))))
                .path("content");
        assertEquals(Set.of("kind", "members"), keys(content));
        assertEquals("object", content.path("kind").asText());
        JsonNode members = content.path("members");
        assertEquals(8, members.size(), "member order and count survive completely");
        assertEquals("report_markdown", members.get(0).path("name").asText());
        String body = MAPPER.writeValueAsString(content);
        assertTrue(body.contains("# 报告"), "long product text must not be truncated");
        assertEquals(500, body.split("很长的正文", -1).length - 1,
                "every repetition of the long body must survive");
        JsonNode answer = members.get(1).path("value");
        assertEquals("null", answer.path("kind").asText());
        assertTrue(members.get(2).path("value").path("bool").asBoolean());
        assertEquals("number", members.get(3).path("value").path("kind").asText());
        assertEquals(0, new BigDecimal("0.1").compareTo(
                new BigDecimal(members.get(3).path("value").path("number").asText())));
        assertEquals(0, new BigDecimal("3000000000").compareTo(
                new BigDecimal(members.get(4).path("value").path("number").asText())),
                "integers must stay exact longs, not doubles");
        assertEquals(-7, members.get(5).path("value").path("number").asInt());
        JsonNode artifacts = members.get(6).path("value");
        assertEquals("list", artifacts.path("kind").asText());
        assertEquals(2, artifacts.path("items").size());
        assertEquals("artifactId", artifacts.path("items").get(0).path("members").get(0).path("name").asText());
        assertEquals("a1", artifacts.path("items").get(0).path("members").get(0).path("value").path("text").asText());
        JsonNode empty = members.get(7).path("value");
        assertEquals("object", empty.path("kind").asText());
        assertEquals(0, empty.path("members").size());
    }

    @Test
    void nullOrMissingContentDecodesToTheNullKind() throws Exception {
        JsonNode explicitNull = json(OutputProjectionMapper.output(row(
                "runId", "run_1", "outputRef", "out_1", "content", null)));
        assertEquals("null", explicitNull.path("content").path("kind").asText());
        JsonNode missing = json(OutputProjectionMapper.output(row(
                "runId", "run_1", "outputRef", "out_1")));
        assertEquals("null", missing.path("content").path("kind").asText());
    }

    @Test
    void grammarViolationsFailLoudly() {
        // A POJO is outside the JSON grammar the value store can produce.
        assertThrows(IllegalArgumentException.class, () -> OutputProjectionMapper.output(row(
                "runId", "run_1", "outputRef", "out_1", "content", new Object())));
        // Non-string member names cannot exist in real JSON and are rejected.
        Map<Object, Object> weird = new LinkedHashMap<>();
        weird.put(42, "value");
        assertThrows(IllegalArgumentException.class, () -> OutputProjectionMapper.output(row(
                "runId", "run_1", "outputRef", "out_1", "content", weird)));
        // Envelope identity is structural.
        assertThrows(IllegalArgumentException.class, () -> OutputProjectionMapper.output(row(
                "outputRef", "out_1", "content", Map.of())));
    }

    @Test
    void legacyOutputsKeepRowIdentityAndContentBodies() throws Exception {
        JsonNode body = json(OutputProjectionMapper.legacyOutputs(row(
                "runId", "run_0",
                "items", List.of(row(
                        "stepId", "step_a", "name", "起草", "status", "completed",
                        "content", row("report", "旧格式正文", "meta", 12))))));
        assertEquals(Set.of("runId", "items"), keys(body));
        JsonNode item = body.path("items").get(0);
        assertEquals(Set.of("stepId", "name", "status", "content"), keys(item));
        assertEquals("旧格式正文", item.path("content").path("members").get(0).path("value").path("text").asText());
        // Missing rows or identity are contract breaks, not empty compatibility lists.
        assertThrows(IllegalArgumentException.class, () -> OutputProjectionMapper.legacyOutputs(row("runId", "run_0")));
        assertThrows(IllegalArgumentException.class, () -> OutputProjectionMapper.legacyOutputs(row(
                "runId", "run_0", "items", List.of(row("stepId", "s", "name", "n")))));
    }

    @Test
    void serializedValueCarriesOnlyGrammarKeys() throws Exception {
        JsonNode content = json(OutputProjectionMapper.output(row(
                "runId", "run_1", "outputRef", "out_1",
                "content", row("k", List.of("v"))))).path("content");
        for (JsonNode member : content.path("members")) {
            assertEquals(Set.of("name", "value"), keys(member));
            JsonNode value = member.path("value");
            Set<String> valueKeys = keys(value);
            assertTrue(valueKeys.isEmpty()
                    || new LinkedHashSet<>(List.of("kind", "text", "bool", "number", "items", "members"))
                            .containsAll(valueKeys));
            assertFalse(value.has("internalState"));
        }
        String body = MAPPER.writeValueAsString(content);
        assertFalse(body.contains("kind\":\"function"), "only the closed kind vocabulary exists");
    }

    private static JsonNode json(Object mapped) throws Exception {
        return MAPPER.readTree(MAPPER.writeValueAsString(mapped));
    }

    private static Set<String> keys(JsonNode node) {
        Set<String> names = new LinkedHashSet<>();
        node.fieldNames().forEachRemaining(names::add);
        return names;
    }
}
