package com.kinlin.ai.projection.copilot;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.kinlin.ai.projection.copilot.dto.CopilotViewQuery;
import com.kinlin.ai.projection.copilot.mapper.CopilotProjectionMapper;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Mapper semantics for the task-Copilot view: identity fields are required, the full
 * upstream wire (question, answers, review, exchanges with action/receipt, decision,
 * model picker) projects field-for-field, and the request echo plus planning patch
 * structures never cross the projection.
 */
class CopilotProjectionMapperTest {

    /** Mirrors the runtime planning interaction {@code view} wire, including internal keys. */
    static Map<String, Object> view() {
        Map<String, Object> wire = new LinkedHashMap<>();
        wire.put("runId", "run_001");
        wire.put("missionId", "mission_001");
        wire.put("latestRunId", "run_002");
        wire.put("taskPermission", "task_collaboration");
        wire.put("status", "waiting_review");
        wire.put("revision", 7);
        wire.put("question", Map.of("questionId", "q-1", "prompt", "包含税费吗?", "choices", List.of("是", "否")));
        wire.put("humanAnswers", List.of(Map.of(
                "questionId", "q-0", "sourceRunId", "run_001", "prompt", "范围?",
                "answer", "全量", "operationId", "a-0", "answeredAt", "2026-10-06T00:00:00Z")));
        wire.put("review", Map.of(
                "subjectId", "mission_001", "subjectType", "mission", "reason", "等待确认",
                "reasonCode", "PLANNER_REVIEW", "canApprove", true, "decisionRejected", false,
                "expectedRunUpdatedAt", "2026-10-06T00:00:00Z"));
        Map<String, Object> operationRequest = new LinkedHashMap<>();
        operationRequest.put("operationId", "m-1");
        operationRequest.put("content", "重跑分析节点");
        operationRequest.put("permission", "task_collaboration");
        Map<String, Object> exchange = new LinkedHashMap<>();
        exchange.put("operationId", "m-1");
        exchange.put("user", "重跑分析节点");
        exchange.put("assistant", "方案已准备");
        exchange.put("createdAt", "2026-10-06T00:01:00Z");
        exchange.put("observedRevision", 6);
        exchange.put("permission", "task_collaboration");
        exchange.put("modelId", "glm-5.3");
        exchange.put("requestedModelId", "glm-5.3");
        exchange.put("reasoningEffort", "high");
        exchange.put("sourceRunId", "run_001");
        exchange.put("operationRequest", operationRequest);
        exchange.put("action", Map.of(
                "kind", "rerun_node", "stepId", "step-2", "expectedRevision", 6,
                "capabilityCatalogRevision", "cat-9", "executionEnvironmentChanged", true,
                "executeStepIds", List.of("step-2", "step-3"), "reusedStepIds", List.of("step-1"),
                "content", "重跑分析节点"));
        wire.put("exchanges", List.of(exchange));
        Map<String, Object> decision = new LinkedHashMap<>();
        decision.put("observationId", "obs-1");
        decision.put("action", "wait");
        decision.put("reason", "等待用户澄清");
        decision.put("taskPlanPatch", Map.of("internal", "PATCH"));
        decision.put("waitFor", Map.of("kind", "until"));
        wire.put("decision", decision);
        wire.put("steps", List.of(Map.of("stepId", "step-1", "name", "分析", "status", "completed")));
        wire.put("modelAvailable", true);
        wire.put("models", List.of(Map.of(
                "id", "zhipu/glm-5.3", "provider", "zhipu", "model", "glm-5.3",
                "reasoningEfforts", List.of("low", "high"), "defaultReasoningEffort", "high")));
        wire.put("defaultModelId", "zhipu/glm-5.3");
        wire.put("permissions", List.of("read_only", "task_collaboration"));
        return wire;
    }

    @Test
    void fullWireProjectsFieldForFieldWithSourceRunAttribution() {
        CopilotViewQuery view = CopilotProjectionMapper.view(view());
        assertEquals("run_001", view.runId());
        assertEquals("mission_001", view.missionId());
        assertEquals("run_002", view.latestRunId());
        assertEquals("waiting_review", view.status());
        assertEquals(7, view.revision());
        assertTrue(view.modelAvailable());
        assertEquals("q-1", view.question().questionId());
        assertEquals(List.of("是", "否"), view.question().choices());
        assertEquals("run_001", view.humanAnswers().get(0).sourceRunId());
        assertTrue(view.review().canApprove());
        assertFalse(view.review().decisionRejected());
        CopilotViewQuery.Exchange exchange = view.exchanges().get(0);
        assertEquals("run_001", exchange.sourceRunId());
        assertEquals(Long.valueOf(6), exchange.observedRevision());
        assertEquals("rerun_node", exchange.action().kind());
        assertEquals(List.of("step-2", "step-3"), exchange.action().executeStepIds());
        assertEquals("cat-9", exchange.action().capabilityCatalogRevision());
        assertEquals("wait", view.decision().action());
        assertEquals("zhipu/glm-5.3", view.models().get(0).id());
        assertEquals(List.of("read_only", "task_collaboration"), view.permissions());
    }

    @Test
    void requestEchoAndPlanningPatchStructuresStayBehindTheProjection() {
        String json = com.fasterxml.jackson.databind.json.JsonMapper.builder().build().valueToTree(
                CopilotProjectionMapper.view(view())).toString();
        assertFalse(json.contains("operationRequest"), json);
        assertFalse(json.contains("taskPlanPatch"), json);
        assertFalse(json.contains("waitFor"), json);
        assertTrue(json.contains("重跑分析节点"));
    }

    @Test
    void optionalSectionsMayBeAbsentButIdentityCannot() {
        Map<String, Object> wire = view();
        wire.put("question", null);
        wire.put("review", null);
        wire.put("decision", null);
        CopilotViewQuery view = CopilotProjectionMapper.view(wire);
        assertNull(view.question());
        assertNull(view.review());
        assertNull(view.decision());
        for (String key : List.of("runId", "missionId", "status", "revision")) {
            Map<String, Object> broken = view();
            broken.put(key, key.equals("revision") ? "not-a-number" : " ");
            assertThrows(IllegalArgumentException.class, () -> CopilotProjectionMapper.view(broken), key);
        }
    }
}
