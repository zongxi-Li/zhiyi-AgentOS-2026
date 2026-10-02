package com.kinlin.ai.projection.workspace;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.projection.workspace.dto.MissionWorkspaceQuery;
import com.kinlin.ai.projection.workspace.dto.WorkspaceEntryQuery;
import com.kinlin.ai.projection.workspace.mapper.WorkspaceProjectionMapper;

/**
 * E2 mapper behavior over the six upstream wire paths: whitelist projection with the
 * E1-review scalar normalization rules (numbers/booleans map to their display strings,
 * objects are omitted — never stringified), per-code diagnostic whitelists, the system
 * document rebuild, and non-echo of every internal sentinel carried by the fixture.
 */
class WorkspaceProjectionMapperTest {
    private static final ObjectMapper MAPPER = new ObjectMapper();

    @Test
    void normalPlanMapsTheTypedEnvelopeAndEchoesNoInternalSentinel() throws Exception {
        MissionWorkspaceQuery workspace = WorkspaceProjectionMapper.workspace(WorkspaceQueryFixture.normalPlan());
        assertInstanceOf(MissionWorkspaceQuery.class, workspace);
        String json = MAPPER.writeValueAsString(workspace);
        assertFalse(json.contains(WorkspaceQueryFixture.SECRET), json);
        var tree = MAPPER.readTree(json);
        assertEquals("mission_1", tree.path("mission").path("missionId").asText());
        assertFalse(tree.path("mission").has("userId"));
        assertFalse(tree.path("mission").has("metadata"));
        assertEquals(2, tree.path("activeGraph").path("taskPlanVersion").asInt());
        assertEquals(9, tree.path("activeGraph").path("nodes").get(0).size()); // reused graph node whitelist
        assertFalse(tree.path("activeGraph").path("nodes").get(0).has("inputSpec"));
        assertFalse(tree.path("activeGraph").path("nodes").get(0).has("modelName"));
        assertFalse(tree.path("activeGraph").path("nodes").get(0).has("metadata"));
        assertFalse(tree.path("graphNodes").get(0).isEmpty());
        assertTrue(tree.path("diagnostics").isEmpty());
        // artifact entry metadata: the duplicated identity keys are gone, entry-level role stays
        var artifactEntry = findEntry(tree, "artifact");
        assertEquals("final_synthesis", artifactEntry.path("logicalRole").asText());
        assertEquals(Map.of(), MAPPER.convertValue(artifactEntry.path("metadata"), Map.class));
        // run entry metadata: the internal run-history marker is dropped
        var runEntry = findEntry(tree, "run");
        assertEquals(Map.of(), MAPPER.convertValue(runEntry.path("metadata"), Map.class));
    }

    @Test
    void systemDocumentIsRebuiltFromPublicFactsOnly() throws Exception {
        MissionWorkspaceQuery workspace = WorkspaceProjectionMapper.workspace(WorkspaceQueryFixture.normalPlan());
        WorkspaceEntryQuery document = workspace.entries().stream()
                .filter(WorkspaceProjectionMapperTest::isSystemDocument).findFirst().orElseThrow();
        String expected = "# 审核合同\n\n查看执行进度\n\n## Current Run\n"
                + "- Run: `run_1`\n- Status: `succeeded`\n- Completed: `" + WorkspaceQueryFixture.TIME + "`\n\n"
                + "## Input attachments\n- **需求说明.md** (`att_1`) - READY, 1024 bytes, `" + "b".repeat(64) + "`\n\n"
                + "## Planned steps\n- **读取材料** (`contract_read`): 提取公开结论\n";
        assertEquals(expected, document.content());
        assertFalse(document.content().contains("Mission metadata"));
        assertFalse(document.content().contains("Constraints"));
    }

    @Test
    void systemDocumentWithoutRunOrPlanKeepsTheUpstreamSectionShapes() {
        MissionWorkspaceQuery noRun = WorkspaceProjectionMapper.workspace(WorkspaceQueryFixture.noRun());
        String noRunContent = noRun.entries().stream()
                .filter(WorkspaceProjectionMapperTest::isSystemDocument).findFirst().orElseThrow().content();
        assertEquals("# 审核合同\n\n查看执行进度\n\n## Current Run\nNo Run has been created.\n\n"
                + "## Input attachments\n- **需求说明.md** (`att_1`) - READY, 1024 bytes, `" + "b".repeat(64) + "`\n",
                noRunContent);
        MissionWorkspaceQuery noPlan = WorkspaceProjectionMapper.workspace(WorkspaceQueryFixture.noPlan());
        String noPlanContent = noPlan.entries().stream()
                .filter(WorkspaceProjectionMapperTest::isSystemDocument).findFirst().orElseThrow().content();
        assertTrue(noPlanContent.contains("## Planned steps"));
        assertFalse(noPlanContent.contains("## Mission metadata"));
    }

    @Test
    void userAndArtifactContentPassesThroughByteForByte() {
        Map<String, Object> wire = WorkspaceQueryFixture.normalPlan();
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> entries = new ArrayList<>((List<Map<String, Object>>) wire.get("entries"));
        entries.add(new LinkedHashMap<>(Map.of(
                "entryId", "artifact:custom", "kind", "artifact", "name", "notes.md", "group", "steps",
                "displayOrder", 5, "attemptCount", 0, "artifactCount", 0, "metadata", Map.of(),
                "content", "用户正文\n\n## 不受影响的章节\n```json\n{\"keep\": true}\n```\n")));
        wire.put("entries", entries);
        MissionWorkspaceQuery workspace = WorkspaceProjectionMapper.workspace(wire);
        assertEquals("用户正文\n\n## 不受影响的章节\n```json\n{\"keep\": true}\n```\n",
                workspace.entries().stream().filter(entry -> "artifact:custom".equals(entry.entryId()))
                        .findFirst().orElseThrow().content());
    }

    @Test
    void sixUpstreamPathsKeepTheirDiagnosticsAndUsability() throws Exception {
        String noPlan = MAPPER.writeValueAsString(
                WorkspaceProjectionMapper.workspace(WorkspaceQueryFixture.noPlan()));
        assertTrue(noPlan.contains("PLAN_SNAPSHOT_UNRESOLVED"));
        var details = MAPPER.readTree(noPlan).path("diagnostics").get(0).path("details");
        assertEquals("run_1", details.path("runId").asText());
        assertFalse(details.has("taskPlanVersion")); // abnormal pointer omitted, diagnostic stays

        String noRun = MAPPER.writeValueAsString(WorkspaceProjectionMapper.workspace(WorkspaceQueryFixture.noRun()));
        var noRunTree = MAPPER.readTree(noRun);
        assertTrue(noRunTree.path("diagnostics").get(0).path("details").isEmpty());
        assertFalse(noRunTree.has("activeRun"));
        assertFalse(noRunTree.has("activeGraph"));

        String deferred = MAPPER.writeValueAsString(
                WorkspaceProjectionMapper.workspace(WorkspaceQueryFixture.deferredFallback()));
        var deferredDetails = MAPPER.readTree(deferred).path("diagnostics").get(0).path("details");
        assertEquals("running", deferredDetails.path("runtimeStatus").asText());
        assertEquals("planning", deferredDetails.path("lifecyclePhase").asText());
        assertFalse(deferredDetails.has("errorCode")); // null detail value normalizes to absent

        String legacy = MAPPER.writeValueAsString(
                WorkspaceProjectionMapper.workspace(WorkspaceQueryFixture.legacyArtifact()));
        var legacyTree = MAPPER.readTree(legacy);
        assertEquals(1, legacyTree.path("diagnostics").get(0).path("details").path("count").asLong());
        var legacyEntry = findEntry(legacyTree, "artifact");
        assertEquals("legacy_artifact", legacyEntry.path("artifactType").asText());

        String missing = MAPPER.writeValueAsString(
                WorkspaceProjectionMapper.workspace(WorkspaceQueryFixture.missingTask()));
        var missingTree = MAPPER.readTree(missing);
        assertEquals(2, missingTree.path("diagnostics").size());
        assertEquals("ghost_task", missingTree.path("diagnostics").get(0).path("details").path("semanticTaskKey").asText());
        var orphan = missingTree.path("graphNodes").get(0);
        assertFalse(orphan.has("taskId"));
        assertFalse(orphan.has("semanticTaskKey"));
        assertFalse(orphan.has("status"));
    }

    @Test
    void confidenceNormalizesExactlyLikeTheFrontendTextReader() throws Exception {
        assertMetadataField("confidence", "0.87", "0.87");
        assertMetadataField("confidence", 0.87, "0.87");
        assertMetadataField("confidence", 42, "42");
        assertMetadataField("confidence", 2.0, "2"); // JS prints integral doubles without a fraction
        assertMetadataField("confidence", true, "true");
        assertMetadataField("confidence", Map.of("internal", "x"), null);
        assertMetadataField("confidence", null, null);
        assertMetadataField("confidence", Double.NaN, null);
        assertMetadataField("confidence", Double.POSITIVE_INFINITY, null);
    }

    @Test
    void referenceListsFilterPerElementLikeTheFrontendListReader() throws Exception {
        // the E1 review's extracted-reader example: ["ref-a",42,true,{internal:SECRET},null] -> ["ref-a","42","true"]
        List<Object> mixed = new ArrayList<>();
        mixed.add("ref-a");
        mixed.add(42);
        mixed.add(true);
        mixed.add(Map.of("internal", WorkspaceQueryFixture.SECRET));
        mixed.add(null);
        Map<String, Object> metadata = new LinkedHashMap<>();
        metadata.put("evidenceRefs", mixed);
        String json = MAPPER.writeValueAsString(WorkspaceProjectionMapper.workspace(metadataWorkspace(metadata)));
        assertFalse(json.contains(WorkspaceQueryFixture.SECRET));
        assertEquals(List.of("ref-a", "42", "true"),
                MAPPER.convertValue(MAPPER.readTree(json).path("entries").get(0).path("metadata").path("evidenceRefs"),
                        List.class));
        assertMetadataField("evidence_refs", "not-an-array", null); // list() renders non-arrays empty
        assertMetadataField("traceLinks", List.of(), List.of());
    }

    @Test
    void kindCandidatesAndAgentNamesFollowTheirOwnReaderRules() throws Exception {
        assertMetadataField("schema", Map.of("columns", List.of()), null); // execution schema never stringified
        assertMetadataField("artifact_kind", "report", "report");
        assertMetadataField("artifactKind", 7, "7");
        assertMetadataField("schemaName", "ContractSchema", "ContractSchema");
        assertMetadataField("agentName", 42, "42"); // runDocument safeText accepts numbers
        assertMetadataField("agent", true, null); // safeText nulls booleans
        assertMetadataField("agentName", "审查员", "审查员");
    }

    @Test
    void runtimeJoinKeysStayStringTypedAndPlanVersionsStayExact() throws Exception {
        assertMetadataField("outputRef", 42, null); // TaskEditor's typeof guard never sees numbers
        assertMetadataField("runtimeStatus", "succeeded", "succeeded");
        assertMetadataField("taskPlanVersion", 2, 2);
        assertMetadataField("taskPlanVersion", "2", 2);
        assertMetadataField("taskPlanVersion", 2.5, null);
        assertMetadataField("taskPlanVersion", 9007199254740993L, null);
        assertMetadataField("taskPlanVersion", Map.of("v", 2), null);
    }

    @Test
    void structuralContractViolationsFailLoudly() {
        Map<String, Object> wire = minimalWire();
        @SuppressWarnings("unchecked")
        Map<String, Object> entry = (Map<String, Object>) ((List<Object>) wire.get("entries")).get(0);
        entry.remove("entryId");
        assertThrows(IllegalArgumentException.class, () -> WorkspaceProjectionMapper.workspace(wire));

        Map<String, Object> legacy = WorkspaceQueryFixture.legacyArtifact();
        Map<String, Object> details = diagnosticDetails(legacy, "LEGACY_ARTIFACT_IDENTITY");
        details.put("count", -1);
        replaceDiagnosticDetails(legacy, "LEGACY_ARTIFACT_IDENTITY", details);
        assertThrows(IllegalArgumentException.class, () -> WorkspaceProjectionMapper.workspace(legacy));
    }

    @Test
    void numberDisplaysMatchJavaScriptAcrossExponentAndPrecisionBoundaries() throws Exception {
        assertMetadataField("confidence", 1e-7, "1e-7");
        assertMetadataField("confidence", 1e-6, "0.000001");
        assertMetadataField("confidence", 1e20, "100000000000000000000");
        assertMetadataField("confidence", 1e21, "1e+21");
        assertMetadataField("confidence", 0.1f, "0.10000000149011612");
        assertMetadataField("confidence", 9007199254740993L, "9007199254740992");
        assertMetadataField("confidence", -0.0, "0");
        assertMetadataField("confidence", Double.MIN_VALUE, "5e-324");
        assertMetadataField("confidence", Double.MAX_VALUE, "1.7976931348623157e+308");
        assertMetadataField("confidence", new java.math.BigDecimal("0.10000000000000000001"), "0.1");
        assertMetadataField("agentName", 1000000000000000128d, "1000000000000000100");
        assertMetadataField("evidenceRefs", List.of(1e-7, 0.1f, 9007199254740993L),
                List.of("1e-7", "0.10000000149011612", "9007199254740992"));
    }

    @Test
    void missingNullOrWrongTypedRequiredCollectionsNeverBecomeEmptySuccess() {
        for (String field : List.of("runs", "entries", "graphNodes", "inputAttachments", "diagnostics")) {
            var missing = minimalWire();
            missing.remove(field);
            assertThrows(IllegalArgumentException.class, () -> WorkspaceProjectionMapper.workspace(missing), field);
            for (Object invalid : new Object[]{null, "invalid", Map.of()}) {
                var wire = minimalWire();
                wire.put(field, invalid);
                assertThrows(IllegalArgumentException.class, () -> WorkspaceProjectionMapper.workspace(wire), field);
            }
        }
    }

    @Test
    void attachmentCountsKeepTheExactDecodedInteger() {
        var attachment = WorkspaceQueryFixture.attachment();
        attachment.put("sizeBytes", Math.nextDown(0x1p63));
        var wire = minimalWire();
        wire.put("inputAttachments", List.of(attachment));
        assertEquals(9223372036854774784L, WorkspaceProjectionMapper.workspace(wire)
                .inputAttachments().get(0).sizeBytes());
    }

    private static Map<String, Object> diagnosticDetails(Map<String, Object> wire, String code) {
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> diagnostics = (List<Map<String, Object>>) wire.get("diagnostics");
        @SuppressWarnings("unchecked")
        Map<String, Object> diagnostic = (Map<String, Object>) diagnostics.stream()
                .filter(item -> code.equals(item.get("code"))).findFirst().orElseThrow();
        @SuppressWarnings("unchecked")
        Map<String, Object> details = (Map<String, Object>) diagnostic.get("details");
        return new LinkedHashMap<>(details);
    }

    private static void replaceDiagnosticDetails(Map<String, Object> wire, String code, Map<String, Object> details) {
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> diagnostics = (List<Map<String, Object>>) wire.get("diagnostics");
        for (Map<String, Object> diagnostic : diagnostics) {
            if (code.equals(diagnostic.get("code"))) { diagnostic.put("details", details); }
        }
    }

    private static void assertMetadataField(String key, Object wireValue, Object expected) throws Exception {
        Map<String, Object> metadata = new LinkedHashMap<>();
        metadata.put(key, wireValue);
        String json = MAPPER.writeValueAsString(WorkspaceProjectionMapper.workspace(metadataWorkspace(metadata)));
        var field = MAPPER.readTree(json).path("entries").get(0).path("metadata").path(key);
        if (expected == null) {
            assertTrue(field.isMissingNode(), key + " should be omitted for " + wireValue + " but was " + field);
        } else if (expected instanceof List<?> list) {
            assertEquals(list, MAPPER.convertValue(field, List.class));
        } else {
            assertEquals(String.valueOf(expected), field.asText());
        }
    }

    /** Minimal valid no-run envelope whose single artifact entry carries the crafted metadata. */
    private static Map<String, Object> metadataWorkspace(Map<String, Object> metadata) {
        Map<String, Object> wire = minimalWire();
        @SuppressWarnings("unchecked")
        Map<String, Object> entry = (Map<String, Object>) ((List<Object>) wire.get("entries")).get(0);
        entry.put("metadata", metadata);
        return wire;
    }

    private static Map<String, Object> minimalWire() {
        Map<String, Object> mission = new LinkedHashMap<>();
        mission.put("missionId", "mission_1");
        mission.put("userId", WorkspaceQueryFixture.SECRET);
        mission.put("goal", "审核合同");
        mission.put("description", "");
        mission.put("metadata", Map.of("identityGeneration", WorkspaceQueryFixture.SECRET));
        mission.put("createdAt", WorkspaceQueryFixture.TIME);
        mission.put("updatedAt", WorkspaceQueryFixture.TIME);
        mission.put("status", "active");
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("entryId", "artifact:custom");
        entry.put("kind", "artifact");
        entry.put("name", "notes.md");
        entry.put("group", "steps");
        entry.put("displayOrder", 0);
        entry.put("attemptCount", 0);
        entry.put("artifactCount", 0);
        entry.put("metadata", Map.of());
        Map<String, Object> wire = new LinkedHashMap<>();
        wire.put("mission", mission);
        wire.put("runs", List.of());
        wire.put("entries", List.of(entry));
        wire.put("graphNodes", List.of());
        wire.put("inputAttachments", List.of());
        wire.put("diagnostics", List.of());
        return wire;
    }

    private static JsonNode findEntry(JsonNode workspace, String kind) {
        for (JsonNode entry : workspace.path("entries")) {
            if (kind.equals(entry.path("kind").asText())) { return entry; }
        }
        throw new AssertionError("no entry of kind " + kind);
    }

    private static boolean isSystemDocument(WorkspaceEntryQuery entry) {
        return "overview:mission.md".equals(entry.entryId()) && "virtual_document".equals(entry.kind());
    }
}
