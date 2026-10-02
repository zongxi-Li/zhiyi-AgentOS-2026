package com.kinlin.ai.projection.workspace;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;

import org.junit.jupiter.api.Test;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.projection.graph.dto.GraphDisplayQuery;
import com.kinlin.ai.projection.graph.dto.GraphEdgeQuery;
import com.kinlin.ai.projection.graph.dto.GraphNodeQuery;
import com.kinlin.ai.projection.workspace.dto.MissionWorkspaceQuery;
import com.kinlin.ai.projection.workspace.dto.WorkspaceAttachmentQuery;
import com.kinlin.ai.projection.workspace.dto.WorkspaceDiagnosticDetailsQuery;
import com.kinlin.ai.projection.workspace.dto.WorkspaceDiagnosticQuery;
import com.kinlin.ai.projection.workspace.dto.WorkspaceEntryMetadataQuery;
import com.kinlin.ai.projection.workspace.dto.WorkspaceEntryQuery;
import com.kinlin.ai.projection.workspace.dto.WorkspaceGraphNodeQuery;
import com.kinlin.ai.projection.workspace.dto.WorkspaceGraphQuery;
import com.kinlin.ai.projection.workspace.dto.WorkspaceMissionQuery;
import com.kinlin.ai.projection.workspace.dto.WorkspaceRunSummaryQuery;

/**
 * E1 contract baseline: the Workspace DTO family serializes exactly its whitelisted key
 * sets with the upstream exclude_none shape (null absent, empty metadata {@code {}}), the
 * original wire aliases survive, and every frontend consumption path stays addressable.
 * The wire fixture maps are E2 mapper inputs; here only their path contract is pinned.
 */
class WorkspaceProjectionSerializationTest {
    private static final ObjectMapper MAPPER = new ObjectMapper();

    @Test
    void envelopeSerializesExactlyTheWhitelistedKeySet() throws Exception {
        JsonNode json = MAPPER.readTree(MAPPER.writeValueAsString(fullEnvelope()));
        assertEquals(Set.of("mission", "activeRun", "activeGraph", "runs", "entries",
                "graphNodes", "inputAttachments", "diagnostics"), fieldNames(json));
    }

    @Test
    void everyNestedModelSerializesItsDocumentedWhitelist() throws Exception {
        JsonNode json = MAPPER.readTree(MAPPER.writeValueAsString(fullEnvelope()));
        assertEquals(Set.of("missionId", "goal", "description", "status", "createdAt", "updatedAt"),
                fieldNames(json.path("mission")));
        assertEquals(Set.of("runId", "status", "parentRunId", "sourceRunId", "createdAt", "completedAt", "isActive"),
                fieldNames(json.path("activeRun")));
        assertEquals(Set.of("graphId", "graphVersion", "missionId", "taskPlanVersion", "objective",
                "complexityLevel", "nodes", "edges"), fieldNames(json.path("activeGraph")));
        assertEquals(Set.of("acgNodeId", "nodeType", "name", "semanticTaskKey", "taskId", "identityQuality",
                "displayOrder", "status", "attemptId", "artifactCount", "artifactIds"),
                fieldNames(json.path("graphNodes").get(0)));
        assertEquals(Set.of("entryId", "kind", "name", "group", "title", "parentEntryId", "displayOrder",
                "semanticTaskKey", "artifactKey", "taskId", "logicalRole", "objective", "dependencyKeys",
                "attemptCount", "latestAttemptId", "artifactCount", "artifactId", "contentRef", "artifactType",
                "mediaType", "checksum", "attemptId", "acgNodeId", "disposition", "sourceRunId",
                "identityQuality", "createdAt", "runId", "status", "blueprintId", "graphId", "graphVersion",
                "parentRunId", "completedAt", "isActive", "content", "metadata"),
                fieldNames(json.path("entries").get(0)));
        assertEquals(Set.of("attachmentId", "originalFilename", "mimeType", "extension", "sizeBytes", "sha256",
                "status", "extractedContentRef", "characterCount", "parser", "parseError", "createdAt", "updatedAt"),
                fieldNames(json.path("inputAttachments").get(0)));
        assertEquals(Set.of("code", "message", "severity", "details"), fieldNames(json.path("diagnostics").get(0)));
    }

    @Test
    void metadataWhitelistKeepsTheOriginalWireAliases() throws Exception {
        JsonNode json = MAPPER.readTree(MAPPER.writeValueAsString(fullEnvelope()));
        assertEquals(Set.of("outputRef", "outputSummary", "runtimeStatus", "taskPlanVersion",
                "artifactKind", "artifact_kind", "schema", "schemaName",
                "evidenceRefs", "evidence_refs", "upstreamInputs", "sourceStepIds",
                "traceLinks", "traceRefs", "confidence", "agentName", "agent"),
                fieldNames(json.path("entries").get(0).path("metadata")));
        assertEquals(Set.of("runId", "acgNodeId", "taskId", "semanticTaskKey", "count", "taskPlanVersion",
                "runtimeStatus", "lifecyclePhase", "errorCode"), fieldNames(json.path("diagnostics").get(0).path("details")));
        // underscore aliases must survive byte-for-byte for artifactProjection's candidate chains
        assertTrue(json.path("entries").get(0).path("metadata").has("artifact_kind"));
        assertTrue(json.path("entries").get(0).path("metadata").has("evidence_refs"));
    }

    @Test
    void nullFieldsStayAbsentAndEmptyMetadataSerializesAsAnEmptyObject() throws Exception {
        MissionWorkspaceQuery sparse = new MissionWorkspaceQuery(
                new WorkspaceMissionQuery("mission_1", "审核合同", "", "active", WorkspaceQueryFixture.TIME, null),
                null, null, List.of(), List.of(
                        new WorkspaceEntryQuery("folder:overview", "folder", "Overview", "overview",
                                null, null, 0, null, null, null, null, null, List.of(), 0, null, 0,
                                null, null, null, null, null, null, null, null, null, null,
                                null, null, null, null, null, null, null, null, null, null,
                                WorkspaceEntryMetadataQuery.empty())),
                List.of(), List.of(),
                List.of(new WorkspaceDiagnosticQuery("NO_ACTIVE_RUN", "Mission has no Run available.", "info",
                        new WorkspaceDiagnosticDetailsQuery(null, null, null, null, null, null, null, null, null))));
        JsonNode json = MAPPER.readTree(MAPPER.writeValueAsString(sparse));
        assertFalse(json.has("activeRun"));
        assertFalse(json.has("activeGraph"));
        assertFalse(json.path("mission").has("updatedAt"));
        assertTrue(json.path("mission").has("description")); // empty string is a value, not a null
        assertEquals("", json.path("mission").path("description").asText());
        JsonNode entry = json.path("entries").get(0);
        assertEquals(0, entry.path("displayOrder").asInt()); // primitives keep the upstream default on the wire
        assertEquals(Map.of(), MAPPER.convertValue(entry.path("metadata"), Map.class));
        assertEquals(Map.of(), MAPPER.convertValue(json.path("diagnostics").get(0).path("details"), Map.class));
        assertEquals(6, json.size()); // mission + runs + entries + graphNodes + inputAttachments + diagnostics
    }

    @Test
    void verifiedFrontendConsumptionPathsStayAddressable() throws Exception {
        JsonNode json = MAPPER.readTree(MAPPER.writeValueAsString(fullEnvelope()));
        JsonNode taskEntry = json.path("entries").get(0).path("metadata");
        // TaskEditor/RuntimeInspector: entry.metadata.outputRef (typeof-string guarded)
        assertEquals("content_ref_1", taskEntry.path("outputRef").asText());
        // ProjectTaskExecutionInspector: entry.metadata.runtimeStatus
        assertEquals("succeeded", taskEntry.path("runtimeStatus").asText());
        // ProjectGraphInspector: graph.taskPlanVersion ?? entry.metadata.taskPlanVersion
        assertEquals(2, json.path("activeGraph").path("taskPlanVersion").asInt());
        assertEquals(2, taskEntry.path("taskPlanVersion").asInt());
        // artifactProjection: kind candidates, reference lists and confidence all scalar-typed
        assertEquals("run_deliverable", taskEntry.path("artifactKind").asText());
        assertEquals("req-evidence", taskEntry.path("evidenceRefs").get(0).asText());
        assertEquals("0.87", taskEntry.path("confidence").asText());
        // runProgress navigator: graphNodes artifact membership
        assertEquals("artifact_1", json.path("graphNodes").get(0).path("artifactIds").get(0).asText());
        // PLAN_SNAPSHOT_UNRESOLVED details carry the exact public plan version
        assertEquals(2, json.path("diagnostics").get(0).path("details").path("taskPlanVersion").asInt());
    }

    @Test
    void wireFixturesCoverTheSixUpstreamPathsWithTheirSentinels() {
        Map<String, Object> normal = WorkspaceQueryFixture.normalPlan();
        assertTrue(WorkspaceQueryFixture.MISSION_MD_LEAK.contains("## Mission metadata"));
        assertTrue(WorkspaceQueryFixture.MISSION_MD_LEAK.contains("Constraints:"));
        @SuppressWarnings("unchecked")
        Map<String, Object> mission = (Map<String, Object>) normal.get("mission");
        assertTrue(((Map<String, Object>) mission.get("metadata")).containsKey("identityGeneration"));
        @SuppressWarnings("unchecked")
        Map<String, Object> artifact = (Map<String, Object>) ((List<Map<String, Object>>) normal.get("entries"))
                .stream().filter(item -> "artifact".equals(item.get("kind"))).findFirst().orElseThrow();
        assertTrue(((Map<String, Object>) artifact.get("metadata")).containsKey("identityVersion"));

        assertEquals("PLAN_SNAPSHOT_UNRESOLVED", code(WorkspaceQueryFixture.noPlan()));
        assertEquals("NO_ACTIVE_RUN", code(WorkspaceQueryFixture.noRun()));
        assertEquals("PLANNING_PROJECTION_PENDING", code(WorkspaceQueryFixture.deferredFallback()));
        assertEquals("LEGACY_ARTIFACT_IDENTITY", code(WorkspaceQueryFixture.legacyArtifact()));
        assertEquals("TASK_PLAN_TASK_NOT_FOUND", code(WorkspaceQueryFixture.missingTask()));
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> missing = (List<Map<String, Object>>) WorkspaceQueryFixture.missingTask().get("diagnostics");
        assertEquals("GRAPH_TASK_NOT_FOUND", missing.get(1).get("code"));
    }

    private static String code(Map<String, Object> envelope) {
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> diagnostics = (List<Map<String, Object>>) envelope.get("diagnostics");
        return (String) diagnostics.get(0).get("code");
    }

    private static Set<String> fieldNames(JsonNode node) {
        Set<String> names = new TreeSet<>();
        node.fieldNames().forEachRemaining(names::add);
        return names;
    }

    /** Every field of every DTO populated once, so closure asserts the full shape. */
    private static MissionWorkspaceQuery fullEnvelope() {
        WorkspaceEntryMetadataQuery metadata = new WorkspaceEntryMetadataQuery(
                "content_ref_1", "已生成阶段结论", "succeeded", 2,
                "run_deliverable", "run_deliverable", "contract_v2", "ContractSchema",
                List.of("req-evidence"), List.of("req-evidence"), List.of("node_0"), List.of("node_0"),
                List.of("trace_1"), List.of("trace_1"), "0.87", "审查员", "审查员");
        WorkspaceEntryQuery entry = new WorkspaceEntryQuery(
                "task:contract_read", "task", "读取材料", "steps", "读取材料", "folder:steps", 1,
                "contract_read", "primary", "task_1", "task", "提取公开结论", List.of("dep_1"), 2,
                "attempt_1", 1, "artifact_1", "content_ref_1", "run_deliverable", "text/markdown",
                "a".repeat(64), "attempt_1", "node_1", "GENERATED", "run_0", "canonical",
                WorkspaceQueryFixture.TIME, "run_1", "completed", "blueprint_1", "graph_1", 3,
                "run_0", WorkspaceQueryFixture.TIME, true, "用户正文", metadata);
        return new MissionWorkspaceQuery(
                new WorkspaceMissionQuery("mission_1", "审核合同", "查看执行进度", "active",
                        WorkspaceQueryFixture.TIME, WorkspaceQueryFixture.TIME),
                new WorkspaceRunSummaryQuery("run_1", "succeeded", "run_0", "run_0",
                        WorkspaceQueryFixture.TIME, WorkspaceQueryFixture.TIME, true),
                new WorkspaceGraphQuery("graph_1", 3, "mission_1", 2, "审核合同", "standard",
                        List.of(new GraphNodeQuery("node_1", "agent", "读取材料", "描述", "目标", "审查员",
                                "capability", "sequential",
                                new GraphDisplayQuery("contract_read", "task_1", "task", "source", "审查员",
                                        List.of("skill_1"), List.of("dep_1"), 0))),
                        List.of(new GraphEdgeQuery("edge_1", "node_1", "node_2", "dependency", "active",
                                new GraphDisplayQuery(null, null, null, null, null, List.of(), List.of(), null)))),
                List.of(new WorkspaceRunSummaryQuery("run_0", "failed", null, null,
                        WorkspaceQueryFixture.TIME, WorkspaceQueryFixture.TIME, false)),
                List.of(entry),
                List.of(new WorkspaceGraphNodeQuery("node_1", "agent", "读取材料", "contract_read",
                        "task_1", "canonical", 0, "succeeded", "attempt_1", 1, List.of("artifact_1"))),
                List.of(new WorkspaceAttachmentQuery("att_1", "需求说明.md", "text/markdown", "md",
                        1024, "b".repeat(64), "READY", "content_ref_0", 512, "parser", "E_ATTACHMENT_PARSE",
                        WorkspaceQueryFixture.TIME, WorkspaceQueryFixture.TIME)),
                List.of(new WorkspaceDiagnosticQuery("PLAN_SNAPSHOT_UNRESOLVED", "计划指针不可解析。", "warning",
                        new WorkspaceDiagnosticDetailsQuery("run_1", "node_9", "task_9", "ghost_task",
                                1L, 2, "running", "planning", "E_PLANNING"))));
    }
}
