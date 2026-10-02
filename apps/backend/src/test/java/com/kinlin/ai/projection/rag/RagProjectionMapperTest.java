package com.kinlin.ai.projection.rag;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.projection.rag.mapper.RagProjectionMapper;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Wire contract for the typed RAG query and document-list projections: the
 * frontend reader shape (answer/sources/confidence, doc_id/filename/upload_time),
 * typed source rows replacing the raw map list, and loud failures.
 */
class RagProjectionMapperTest {
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private static Map<String, Object> row(Object... keyValues) {
        Map<String, Object> result = new LinkedHashMap<>();
        for (int index = 0; index < keyValues.length; index += 2) {
            result.put(String.valueOf(keyValues[index]), keyValues[index + 1]);
        }
        return result;
    }

    private static JsonNode json(Object mapped) throws Exception {
        return MAPPER.readTree(MAPPER.writeValueAsString(mapped));
    }

    @Test
    void queryKeepsAnswerSourcesConfidenceWithoutRawMaps() throws Exception {
        List<Map<String, Object>> sources = List.of(
                row("title", "来源一", "url", "https://a", "content", "片段", "internal", "drop"),
                row("title", 42, "url", "https://b"),
                row("title", "来源二"));
        JsonNode body = json(RagProjectionMapper.query("这是答案", sources, 0.87));
        assertEquals("这是答案", body.path("answer").asText());
        assertEquals(3, body.path("sources").size());
        assertEquals("来源一", body.path("sources").get(0).path("title").asText());
        assertFalse(body.path("sources").get(1).has("title"), "non-string fields drop per source");
        assertFalse(MAPPER.writeValueAsString(body).contains("drop"));
        assertEquals(0, Double.compare(0.87, body.path("confidence").asDouble()));
    }

    @Test
    void documentsKeepReaderFieldsAndDropMetadataBag() throws Exception {
        Map<String, Object> wire = row(
                "documents", List.of(row(
                        "doc_id", "d1", "filename", "合同.pdf", "upload_time", "2026-10-02",
                        "role_id", "r1", "metadata", Map.of("internal", "drop"))),
                "count", 1);
        JsonNode body = json(RagProjectionMapper.documents(wire));
        assertEquals(1, body.path("count").asLong());
        JsonNode doc = body.path("documents").get(0);
        assertEquals("d1", doc.path("doc_id").asText());
        assertFalse(MAPPER.writeValueAsString(body).contains("metadata"));
        assertTrue(MAPPER.writeValueAsString(body).contains("合同.pdf"));
    }

    @Test
    void damagedResultsFailLoudly() {
        assertThrows(IllegalArgumentException.class, () -> RagProjectionMapper.query(null, List.of(), 1.0));
        assertThrows(IllegalArgumentException.class,
                () -> RagProjectionMapper.documents(row("count", 0)));
        assertThrows(IllegalArgumentException.class, () -> RagProjectionMapper.documents(row(
                "documents", List.of(row("filename", "no-id")), "count", 1)));
    }
}
