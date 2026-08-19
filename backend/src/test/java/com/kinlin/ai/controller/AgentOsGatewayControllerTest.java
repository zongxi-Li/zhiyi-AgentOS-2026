package com.kinlin.ai.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.config.AgentProperties;
import com.kinlin.ai.dto.agentos.AgentOsRunCreateRequest;
import com.kinlin.ai.service.AgentOsGatewayService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.reactive.function.client.WebClient;

import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class AgentOsGatewayControllerTest {

    private MockMvc mockMvc;
    private ObjectMapper objectMapper;
    private RecordingGateway gateway;

    @BeforeEach
    void setUp() {
        objectMapper = new ObjectMapper();
        gateway = new RecordingGateway();
        mockMvc = MockMvcBuilders.standaloneSetup(new AgentOsGatewayController(gateway)).build();
    }

    @Test
    void createRunForwardsOnlyTheV2ContractAndPreservesAccepted() throws Exception {
        gateway.postResponses.put("/ai/agentos/v2/runs", response(202, Map.of(
                "runId", "run_001", "status", "pending", "executionState", Map.of("outputRefs", Map.of())
        )));

        mockMvc.perform(post("/api/agentos/v2/runs")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "title", "合同审查",
                                "workflowId", "legal_contract_review_v1",
                                "clientRequestId", "request-1"
                        ))))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.runId").value("run_001"))
                .andExpect(jsonPath("$._httpStatus").doesNotExist());

        assertEquals("/ai/agentos/v2/runs", gateway.lastPostPath);
        AgentOsRunCreateRequest request = (AgentOsRunCreateRequest) gateway.lastPostBody;
        assertEquals("general", request.domain());
        assertEquals("auto", request.reviewMode());
        assertEquals(Map.of(), request.input());
    }

    @Test
    void resourcesAreStraightProxiesWithoutLegacyRuntimeGraphEndpoints() throws Exception {
        gateway.getResponses.put("/ai/agentos/v2/runs/run_001/graph", response(200, Map.of(
                "runId", "run_001", "nodes", java.util.List.of()
        )));

        mockMvc.perform(get("/api/agentos/v2/runs/run_001/graph"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.runId").value("run_001"));
        assertEquals("/ai/agentos/v2/runs/run_001/graph", gateway.lastGetPath);

        mockMvc.perform(get("/api/agentos/core/workflows/runs/run_001/acg"))
                .andExpect(status().isNotFound());
    }

    @Test
    void outputAndReviewUseOwnedSubresourcePathsAndValidatedDtos() throws Exception {
        String outputPath = "/ai/agentos/v2/runs/run_001/outputs/output:run_001:report:hash";
        gateway.getResponses.put(outputPath, response(200, Map.of("outputRef", "output:run_001:report:hash")));
        mockMvc.perform(get("/api/agentos/v2/runs/run_001/outputs/output:run_001:report:hash"))
                .andExpect(status().isOk());
        assertEquals(outputPath, gateway.lastGetPath);

        String legacyOutputPath = "/ai/agentos/v2/runs/run_001/legacy-outputs";
        gateway.getResponses.put(legacyOutputPath, response(200, Map.of("runId", "run_001", "items", java.util.List.of())));
        mockMvc.perform(get("/api/agentos/v2/runs/run_001/legacy-outputs"))
                .andExpect(status().isOk());
        assertEquals(legacyOutputPath, gateway.lastGetPath);

        String reviewPath = "/ai/agentos/v2/runs/run_001/reviews";
        gateway.postResponses.put(reviewPath, response(200, Map.of("runId", "run_001", "status", "running")));
        mockMvc.perform(post("/api/agentos/v2/runs/run_001/reviews")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"stepId\":\"review\",\"decision\":\"approved\",\"operationId\":\"op-1\"}"))
                .andExpect(status().isOk());
        assertEquals(reviewPath, gateway.lastPostPath);
        assertFalse(gateway.lastPostBody instanceof Map);

        mockMvc.perform(post("/api/agentos/v2/runs/run_001/reviews")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"stepId\":\"review\",\"decision\":\"invented\",\"operationId\":\"op-2\"}"))
                .andExpect(status().isBadRequest());
    }

    private static Map<String, Object> response(int status, Map<String, Object> body) {
        Map<String, Object> result = new LinkedHashMap<>(body);
        result.put(AgentOsGatewayService.INTERNAL_HTTP_STATUS_KEY, status);
        return result;
    }

    private static final class RecordingGateway extends AgentOsGatewayService {
        private final Map<String, Map<String, Object>> getResponses = new HashMap<>();
        private final Map<String, Map<String, Object>> postResponses = new HashMap<>();
        private String lastGetPath;
        private String lastPostPath;
        private Object lastPostBody;

        private RecordingGateway() {
            super(WebClient.builder(), new AgentProperties(), "http://localhost:8000");
        }

        @Override
        public Map<String, Object> get(String path) {
            lastGetPath = path;
            return getResponses.getOrDefault(path, response(404, Map.of("message", "not found")));
        }

        @Override
        public Map<String, Object> post(String path, Object body) {
            lastPostPath = path;
            lastPostBody = body;
            return postResponses.getOrDefault(path, response(404, Map.of("message", "not found")));
        }
    }
}
