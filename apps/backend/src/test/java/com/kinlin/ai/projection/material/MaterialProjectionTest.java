package com.kinlin.ai.projection.material;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.projection.material.mapper.MaterialProjectionMapper;
import org.junit.jupiter.api.Test;
import java.util.HashMap;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.*;

class MaterialProjectionTest {
    private final ObjectMapper json = new ObjectMapper();

    @Test
    void manifestKeepsPublicFactsWithoutOwnershipOrUnknownFields() throws Exception {
        var source = new HashMap<String, Object>(Map.of("manifestId", "m1", "kind", "material",
                "mediaType", "text/plain", "byteLength", 900, "fragmentCount", 2, "sealed", true));
        source.put("ownerId", "SECRET");
        source.put("ownerType", "SECRET");
        source.put("metadata", Map.of("binding", "SECRET"));
        var result = json.readTree(json.writeValueAsString(MaterialProjectionMapper.material(source)));
        assertEquals(6, result.size());
        assertEquals(900, result.get("byteLength").longValue());
        assertTrue(result.get("sealed").booleanValue());
        assertFalse(result.toString().contains("SECRET"));
        source.put("byteLength", new java.math.BigDecimal("12.5"));
        assertThrows(ArithmeticException.class, () -> MaterialProjectionMapper.material(source));
        assertThrows(IllegalArgumentException.class, () -> MaterialProjectionMapper.material(Map.of()));
    }

    @Test
    void attachmentPreservesFailureAndReferencesWithoutStorageOrMetadata() throws Exception {
        var source = new HashMap<String, Object>(Map.of("attachmentId", "a1", "originalFilename", "notes.txt",
                "filename", "notes.txt", "status", "FAILED", "errorCode", "PARSING_FAILED",
                "parseError", "Could not parse this file", "extractedContentRef", "public-ref"));
        source.put("storageKey", "SECRET");
        source.put("ownerUserId", "SECRET");
        source.put("metadata", Map.of("internal", "SECRET"));
        var result = json.readTree(json.writeValueAsString(MaterialProjectionMapper.attachment(source)));
        assertEquals(7, result.size());
        assertEquals("PARSING_FAILED", result.get("errorCode").textValue());
        assertEquals("public-ref", result.get("extractedContentRef").textValue());
        assertFalse(result.toString().contains("SECRET"));
    }
}
