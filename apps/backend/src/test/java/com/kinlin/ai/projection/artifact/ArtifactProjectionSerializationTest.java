package com.kinlin.ai.projection.artifact;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.projection.artifact.dto.ArtifactDetailQuery;
import com.kinlin.ai.projection.artifact.mapper.ArtifactProjectionMapper;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.*;

class ArtifactProjectionSerializationTest {

    static final String SECRET = "内部哨兵-不得出现在公共响应";
    private static final String MANIFEST_CHECKSUM = "a".repeat(64);
    private static final String ARTIFACT_CHECKSUM = "b".repeat(64);
    private static final String FRAGMENT_CHECKSUM = "c".repeat(64);

    private final ObjectMapper jackson = new ObjectMapper();

    @Test
    void identityDetailKeepsFlatShapeAndMergedOverrideValuesWithoutInternalKeys() throws Exception {
        Map<String, Object> wire = identityWire();
        ArtifactDetailQuery detail = ArtifactProjectionMapper.detail(wire);
        String encoded = jackson.writeValueAsString(detail);
        JsonNode json = jackson.readTree(encoded);

        Set<String> keys = new HashSet<>();
        json.fieldNames().forEachRemaining(keys::add);
        assertEquals(Set.of("manifestId", "kind", "mediaType", "checksum", "byteLength", "fragmentCount",
                        "estimatedTokens", "sealed", "createdAt", "artifactId", "missionId", "originRunId",
                        "taskId", "semanticTaskKey", "artifactKey", "acgNodeId", "producerAttemptId", "name",
                        "artifactType", "contentRef", "runId", "disposition", "sourceRunId"),
                keys, "详情投影的平铺键集封闭且不嵌套");

        // 上游合并序 manifest → artifact → binding，后者覆盖同名键；Mapper 只读已合并结果
        assertEquals("2026-03-03T00:00:00Z", json.get("createdAt").asText());
        assertEquals(ARTIFACT_CHECKSUM, json.get("checksum").asText());
        assertEquals("application/pdf", json.get("mediaType").asText());
        assertEquals("GENERATED", json.get("disposition").asText());
        assertTrue(json.get("sourceRunId").isNull());
        assertEquals(1234, json.get("byteLength").asLong());
        assertTrue(json.get("sealed").isBoolean());

        // 内部键（存储归属/分块版本/绑定标识/开放 metadata）不可达
        assertFalse(encoded.contains(SECRET));
        assertFalse(encoded.contains("ownerType"));
        assertFalse(encoded.contains("ownerId"));
        assertFalse(encoded.contains("chunkingVersion"));
        assertFalse(encoded.contains("bindingId"));
        assertFalse(encoded.contains("metadata"));
        assertFalse(encoded.contains("logicalRole"));

        // 投影是取值快照，不追踪 wire 后续修改
        wire.clear();
        assertEquals(encoded, jackson.writeValueAsString(detail));
    }

    @Test
    void manifestOnlyFallbackKeepsManifestValuesAndNullsIdentityFields() throws Exception {
        Map<String, Object> wire = fallbackWire();
        ArtifactDetailQuery detail = ArtifactProjectionMapper.detail(wire);
        String encoded = jackson.writeValueAsString(detail);
        JsonNode json = jackson.readTree(encoded);

        assertEquals("2026-01-01T00:00:00Z", json.get("createdAt").asText(), "fallback 保留 manifest 时间");
        assertEquals(MANIFEST_CHECKSUM, json.get("checksum").asText());
        assertEquals("text/markdown", json.get("mediaType").asText());
        assertEquals("manifest_001", json.get("manifestId").asText());
        for (String field : List.of("artifactId", "missionId", "originRunId", "taskId", "semanticTaskKey",
                "artifactKey", "acgNodeId", "producerAttemptId", "name", "artifactType", "contentRef",
                "runId", "disposition", "sourceRunId")) {
            assertTrue(json.get(field).isNull(), field + " 在 fallback 上为 null");
        }
        assertFalse(encoded.contains(SECRET));
    }

    @Test
    void pageAndFragmentPageKeepEnvelopeKeysCursorAndContentVerbatim() throws Exception {
        Map<String, Object> listWire = Map.of("runId", "run_001",
                "items", List.of(identityWire(), fallbackWire()), "total", 2);
        var page = ArtifactProjectionMapper.page(new HashMap<>(listWire));
        assertEquals("run_001", page.runId());
        assertEquals(2, page.total());
        assertEquals("application/pdf", page.items().get(0).mediaType());
        assertNull(page.items().get(1).artifactId());
        assertThrows(UnsupportedOperationException.class, () -> page.items().clear());

        String longContent = "分片正文不截断：" + "内".repeat(500);
        Map<String, Object> fragment = fragmentRow(longContent);
        Map<String, Object> pageWire = new HashMap<>();
        pageWire.put("manifest", fallbackWire());
        pageWire.put("items", List.of(fragment));
        pageWire.put("nextCursor", "cursor_002");
        var fragmentPage = ArtifactProjectionMapper.fragmentPage(pageWire);
        assertEquals("cursor_002", fragmentPage.nextCursor());
        assertEquals("manifest_001", fragmentPage.manifest().manifestId());
        assertEquals(1, fragmentPage.items().size());
        assertEquals(longContent, fragmentPage.items().get(0).content(), "分片正文逐字保留");
        assertEquals(4, fragmentPage.items().get(0).sequence());
        assertEquals(List.of("step_001"), fragmentPage.items().get(0).sourceRefs());
        assertEquals(List.of("constraint_9"), fragmentPage.items().get(0).constraintRefs());
        assertEquals("passed", fragmentPage.items().get(0).verificationStatus());
        assertTrue(fragmentPage.items().get(0).complete());

        Map<String, Object> lastPage = new HashMap<>();
        lastPage.put("manifest", fallbackWire());
        lastPage.put("items", List.of(fragment));
        lastPage.put("nextCursor", null);
        assertNull(ArtifactProjectionMapper.fragmentPage(lastPage).nextCursor());
    }

    @Test
    void missingRequiredFieldsBadScalarsAndInternalTypesAreRejected() {
        // manifest 侧必需字段缺失
        for (String field : List.of("manifestId", "kind", "mediaType", "byteLength", "fragmentCount",
                "sealed", "createdAt")) {
            Map<String, Object> wire = fallbackWire();
            wire.remove(field);
            assertThrows(RuntimeException.class, () -> ArtifactProjectionMapper.detail(wire), field);
        }
        // identity 命中时 artifact/binding 侧必需字段缺失
        for (String field : List.of("missionId", "originRunId", "taskId", "semanticTaskKey", "artifactKey",
                "acgNodeId", "producerAttemptId", "name", "artifactType", "contentRef", "runId", "disposition")) {
            Map<String, Object> wire = identityWire();
            wire.remove(field);
            assertThrows(RuntimeException.class, () -> ArtifactProjectionMapper.detail(wire), field);
        }
        // 坏标量：负数、坏时间、坏布尔、坏 estimatedTokens
        Map<String, Object> negative = identityWire(); negative.put("byteLength", -1);
        Map<String, Object> badTime = identityWire(); badTime.put("createdAt", SECRET);
        Map<String, Object> badBool = identityWire(); badBool.put("sealed", "true");
        Map<String, Object> badTokens = identityWire(); badTokens.put("estimatedTokens", -3);
        Map<String, Object> floatFragmentCount = identityWire(); floatFragmentCount.put("fragmentCount", 1.5);
        for (Map<String, Object> wire : List.of(negative, badTime, badBool, badTokens, floatFragmentCount)) {
            assertThrows(RuntimeException.class, () -> ArtifactProjectionMapper.detail(wire));
        }
        // 列表信封与分片行契约
        assertThrows(RuntimeException.class, () -> ArtifactProjectionMapper.page(Map.of("runId", "run_001",
                "items", List.of(), "total", -1)));
        assertThrows(RuntimeException.class, () -> ArtifactProjectionMapper.page(Map.of(
                "items", List.of(), "total", 0)));
        for (String field : List.of("fragmentId", "manifestId", "sequence", "checksum", "byteLength",
                "sourceRefs", "constraintRefs", "verificationStatus", "complete", "content")) {
            Map<String, Object> row = fragmentRow("正文");
            row.remove(field);
            Map<String, Object> wire = new HashMap<>();
            wire.put("manifest", fallbackWire());
            wire.put("items", List.of(row));
            wire.put("nextCursor", null);
            assertThrows(RuntimeException.class, () -> ArtifactProjectionMapper.fragmentPage(wire), field);
        }
        Map<String, Object> badRefs = fragmentRow("正文");
        badRefs.put("sourceRefs", List.of(1));
        Map<String, Object> badSequence = fragmentRow("正文");
        badSequence.put("sequence", -1);
        for (Map<String, Object> row : List.of(badRefs, badSequence)) {
            Map<String, Object> wire = new HashMap<>();
            wire.put("manifest", fallbackWire());
            wire.put("items", List.of(row));
            wire.put("nextCursor", null);
            assertThrows(RuntimeException.class, () -> ArtifactProjectionMapper.fragmentPage(wire));
        }
    }

    private Map<String, Object> identityWire() {
        Map<String, Object> wire = fallbackWire();
        wire.put("artifactId", "artifact_001");
        wire.put("missionId", "mission_001");
        wire.put("originRunId", "run_001");
        wire.put("taskId", "task_001");
        wire.put("semanticTaskKey", "analyze");
        wire.put("artifactKey", "primary");
        wire.put("acgNodeId", "node_7");
        wire.put("producerAttemptId", "attempt_001");
        wire.put("name", "尽调报告");
        wire.put("artifactType", "run_deliverable");
        wire.put("contentRef", "manifest_001");
        wire.put("checksum", ARTIFACT_CHECKSUM);        // artifact 覆盖 manifest
        wire.put("mediaType", "application/pdf");       // artifact 覆盖 manifest
        wire.put("createdAt", "2026-02-02T00:00:00Z");  // artifact 覆盖 manifest
        wire.put("metadata", Map.of("logicalRole", "run_deliverable", "identityVersion", SECRET));
        wire.put("bindingId", SECRET);                  // 内部绑定标识，必须被隔离
        wire.put("runId", "run_001");
        wire.put("disposition", "GENERATED");
        wire.put("sourceRunId", null);
        wire.put("createdAt", "2026-03-03T00:00:00Z");  // binding 再覆盖 artifact
        return wire;
    }

    private Map<String, Object> fallbackWire() {
        Map<String, Object> wire = new HashMap<>();
        wire.put("manifestId", "manifest_001");
        wire.put("kind", "artifact");
        wire.put("ownerType", "run");
        wire.put("ownerId", SECRET);
        wire.put("mediaType", "text/markdown");
        wire.put("checksum", MANIFEST_CHECKSUM);
        wire.put("byteLength", 1234);
        wire.put("fragmentCount", 3);
        wire.put("estimatedTokens", 88);
        wire.put("chunkingVersion", SECRET);
        wire.put("sealed", true);
        wire.put("createdAt", "2026-01-01T00:00:00Z");
        return wire;
    }

    private Map<String, Object> fragmentRow(String content) {
        Map<String, Object> row = new HashMap<>();
        row.put("fragmentId", "fragment_001");
        row.put("manifestId", "manifest_001");
        row.put("sequence", 4);
        row.put("checksum", FRAGMENT_CHECKSUM);
        row.put("byteLength", 2048);
        row.put("estimatedTokens", null);
        row.put("sourceRefs", new ArrayList<>(List.of("step_001")));
        row.put("constraintRefs", List.of("constraint_9"));
        row.put("verificationStatus", "passed");
        row.put("complete", true);
        row.put("content", content);
        return row;
    }
}
