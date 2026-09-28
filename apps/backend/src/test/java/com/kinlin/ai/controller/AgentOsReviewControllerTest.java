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
