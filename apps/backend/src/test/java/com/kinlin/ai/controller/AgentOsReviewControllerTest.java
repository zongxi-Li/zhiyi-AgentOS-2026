package com.kinlin.ai.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.exception.AgentOsGatewayExceptionHandler;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/** REVIEW_RECOVERY ownership: review read/apply and failed-step retry. */
class AgentOsReviewControllerTest {

    private MockMvc mockMvc;
    private ObjectMapper objectMapper;
    private RecordingAgentOsGateway gateway;

    @BeforeEach
    void setUp() {
        objectMapper = new ObjectMapper();
        gateway = new RecordingAgentOsGateway();
        mockMvc = MockMvcBuilders.standaloneSetup(new AgentOsReviewController(gateway))
                .setControllerAdvice(new AgentOsGatewayExceptionHandler())
                .build();
    }

    @Test
    void copilotForwardsConversationAndClarificationWithoutLosingStatusOrIds() throws Exception {
        String path = "/ai/agentos/v2/runs/run_001/copilot";
        gateway.getResponses.put(path, RecordingAgentOsGateway.response(200, Map.of(
                "runId", "run_001", "missionId", "mission_001", "latestRunId", "run_002",
                "status", "waiting_review", "revision", 3,
                "question", Map.of("questionId", "q-1", "prompt", "Include tax?", "choices", List.of("yes")),
                "humanAnswers", List.of(Map.of("questionId", "q-0", "sourceRunId", "run_001",
                        "prompt", "范围?", "answer", "全量", "operationId", "a-0",
                        "answeredAt", "2026-10-06T00:00:00Z")),
                "exchanges", List.of(Map.of("operationId", "m-1", "user", "重新分析",
                        "assistant", "方案已准备", "createdAt", "2026-10-06T00:01:00Z",
                        "observedRevision", 2, "sourceRunId", "run_001")),
                "decision", Map.of("observationId", "obs-1", "action", "wait", "reason", "ask",
                        "taskPlanPatch", Map.of("internal", "PATCH")))));
        mockMvc.perform(get("/api/agentos/v2/runs/run_001/copilot"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("waiting_review"))
                .andExpect(jsonPath("$.missionId").value("mission_001"))
                .andExpect(jsonPath("$.latestRunId").value("run_002"))
                .andExpect(jsonPath("$.revision").value(3))
                .andExpect(jsonPath("$.question.questionId").value("q-1"))
                .andExpect(jsonPath("$.humanAnswers[0].questionId").value("q-0"))
                .andExpect(jsonPath("$.humanAnswers[0].answer").value("全量"))
                .andExpect(jsonPath("$.exchanges[0].operationId").value("m-1"))
                .andExpect(jsonPath("$.exchanges[0].user").value("重新分析"))
                .andExpect(jsonPath("$.exchanges[0].sourceRunId").value("run_001"))
                .andExpect(jsonPath("$.decision.action").value("wait"))
                .andExpect(jsonPath("$.decision.taskPlanPatch").doesNotExist());
        assertEquals(path, gateway.lastGetPath);
        gateway.postResponses.put(path + "/answers", RecordingAgentOsGateway.response(202, Map.of("status", "retrying")));
        mockMvc.perform(post("/api/agentos/v2/runs/run_001/copilot/answers")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"questionId\":\"q-1\",\"answer\":\"yes\",\"expectedRevision\":3,\"operationId\":\"a-1\"}"))
                .andExpect(status().isAccepted()).andExpect(jsonPath("$.status").value("retrying"));
        assertEquals(path + "/answers", gateway.lastPostPath);
        assertEquals("q-1", ((Map<?, ?>) gateway.lastPostBody).get("questionId"));
        gateway.postResponses.put(path + "/messages", RecordingAgentOsGateway.response(503, Map.of("detail", "model unavailable")));
        mockMvc.perform(post("/api/agentos/v2/runs/run_001/copilot/messages")
                .contentType(MediaType.APPLICATION_JSON).content("{\"content\":\"hello\",\"operationId\":\"m-1\"}"))
                .andExpect(status().isServiceUnavailable());
    }

    @Test
    void copilotPermissionUsesTheExistingOwnedRunGatewayAndReturnsTaskScope() throws Exception {
        String path = "/ai/agentos/v2/runs/run_001/copilot/permission";
        gateway.postResponses.put(path, RecordingAgentOsGateway.response(200,
                Map.of("missionId", "mission_001", "taskPermission", "read_only")));
        mockMvc.perform(post("/api/agentos/v2/runs/run_001/copilot/permission")
                .contentType(MediaType.APPLICATION_JSON).content("{\"permission\":\"read_only\"}"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.missionId").value("mission_001"));
        assertEquals(path, gateway.lastPostPath);
        assertEquals("read_only", ((Map<?, ?>) gateway.lastPostBody).get("permission"));
    }

    @Test
    void reviewListingUsesTheOwnedSubresourcePath() throws Exception {
        String path = "/ai/agentos/v2/runs/run_001/reviews";
        gateway.getResponses.put(path, RecordingAgentOsGateway.response(200, Map.of(
                "items", List.of(Map.of("stepId", "review", "decision", "approved"))
        )));

        mockMvc.perform(get("/api/agentos/v2/runs/{runId}/reviews", "run_001"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items[0].decision").value("approved"));

        assertEquals(path, gateway.lastGetPath);
    }

    @Test
    void copilotActionsPreserveTargetRevisionAndRuntimeReceipt() throws Exception {
        String path = "/ai/agentos/v2/runs/run_001/copilot/actions";
        gateway.postResponses.put(path + "/preview", RecordingAgentOsGateway.response(200, Map.of(
                "action", Map.of("stepId", "B", "expectedRevision", 7))));
        mockMvc.perform(post("/api/agentos/v2/runs/run_001/copilot/actions/preview")
                .contentType(MediaType.APPLICATION_JSON).content("{\"kind\":\"rerun_node\",\"stepId\":\"B\",\"operationId\":\"p\",\"permission\":\"task_collaboration\"}"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.action.stepId").value("B"));
        assertEquals(path + "/preview", gateway.lastPostPath);
        assertEquals("B", ((Map<?, ?>) gateway.lastPostBody).get("stepId"));
        gateway.postResponses.put(path, RecordingAgentOsGateway.response(202, Map.of("receipt", Map.of("runId", "child"))));
        mockMvc.perform(post("/api/agentos/v2/runs/run_001/copilot/actions")
                .contentType(MediaType.APPLICATION_JSON).content("{\"proposalId\":\"p\",\"expectedRevision\":7,\"permission\":\"task_collaboration\"}"))
                .andExpect(status().isAccepted()).andExpect(jsonPath("$.receipt.runId").value("child"));
        assertEquals(7, ((Map<?, ?>) gateway.lastPostBody).get("expectedRevision"));
    }

    @Test
    void applyReviewForwardsTheTypedContractAndValidatesTheDecision() throws Exception {
        String reviewPath = "/ai/agentos/v2/runs/run_001/reviews";
        gateway.postResponses.put(reviewPath, RecordingAgentOsGateway.response(200, Map.of(
                "runId", "run_001", "status", "running")));
        mockMvc.perform(post("/api/agentos/v2/runs/run_001/reviews")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"stepId\":\"review\",\"decision\":\"approved\",\"operationId\":\"op-1\"}"))
                .andExpect(status().isOk());
        assertEquals(reviewPath, gateway.lastPostPath);
        assertFalse(gateway.lastPostBody instanceof Map);

        mockMvc.perform(post("/api/agentos/v2/runs/run_001/reviews")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"stepId\":\"review\",\"decision\":\"invented\",\"operationId\":\"op-2\"}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.code").value("AGENTOS_VALIDATION_ERROR"));
    }

    @Test
    void failedStepRetryForwardsRunStepAndPreservesAcceptedStatus() throws Exception {
        String retryPath = "/ai/agentos/v2/runs/run%20001/steps/design%20step/retry";
        gateway.postResponses.put(retryPath, RecordingAgentOsGateway.response(202, Map.of(
                "runId", "run_002", "status", "pending"
        )));

        mockMvc.perform(post(
                        "/api/agentos/v2/runs/{runId}/steps/{stepId}/retry",
                        "run 001",
                        "design step"
                )
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"clientRequestId\":\"retry-1\",\"mode\":\"successor_run\"}"))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.runId").value("run_002"));

        assertEquals(retryPath, gateway.lastPostPath);
        com.kinlin.ai.dto.agentos.AgentOsRetryRequest request =
                (com.kinlin.ai.dto.agentos.AgentOsRetryRequest) gateway.lastPostBody;
        assertEquals("retry-1", request.clientRequestId());
        assertEquals("operator_requested", request.reason());
        assertEquals("successor_run", request.mode());
    }

    @Test
    void retryRejectsSemanticAndConcreteResourceOverrides() throws Exception {
        for (String forbidden : List.of("taskPlanPatch", "graphPatch", "resourceId", "workerId")) {
            mockMvc.perform(post("/api/agentos/v2/runs/run_1/steps/step_1/retry")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("{\"clientRequestId\":\"retry-1\",\"" + forbidden + "\":{}}"))
                    .andExpect(status().isBadRequest())
                    .andExpect(jsonPath("$.code").value("AGENTOS_INVALID_REQUEST"));
        }
    }
}
