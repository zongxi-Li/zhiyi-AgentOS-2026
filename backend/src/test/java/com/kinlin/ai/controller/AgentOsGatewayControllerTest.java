package com.kinlin.ai.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.config.AgentProperties;
import com.kinlin.ai.dto.agentos.AgentOsMissionCreateRequest;
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
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
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
    void createMissionForwardsOnlyTheV2ContractAndPreservesAccepted() throws Exception {
        gateway.postResponses.put("/ai/agentos/v2/missions", response(202, Map.of(
                "runId", "run_001", "status", "pending", "executionState", Map.of("outputRefs", Map.of())
        )));

        mockMvc.perform(post("/api/agentos/v2/missions")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "title", "合同审查",
                                "workflowId", "legal_contract_review_v1",
                                "materialRefs", List.of("manifest_001"),
                                "clientRequestId", "request-1"
                        ))))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.runId").value("run_001"))
                .andExpect(jsonPath("$._httpStatus").doesNotExist());

        assertEquals("/ai/agentos/v2/missions", gateway.lastPostPath);
        AgentOsMissionCreateRequest request = (AgentOsMissionCreateRequest) gateway.lastPostBody;
        assertEquals("general", request.domain());
        assertEquals("auto", request.reviewMode());
        assertEquals(Map.of(), request.input());
        assertEquals(List.of("manifest_001"), request.materialRefs());
    }

    @Test
    void materialManifestEndpointsPreserveCompleteContentAndReferences() throws Exception {
        String materialPath = "/ai/agentos/v2/materials";
        gateway.postResponses.put(materialPath, response(201, Map.of(
                "manifestId", "manifest_001", "sealed", true
        )));

        String material = "完整材料".repeat(2000);
        mockMvc.perform(post("/api/agentos/v2/materials")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "content", material,
                                "mediaType", "text/plain"
                        ))))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.manifestId").value("manifest_001"));

        assertEquals(materialPath, gateway.lastPostPath);
        com.kinlin.ai.dto.agentos.AgentOsMaterialCreateRequest request =
                (com.kinlin.ai.dto.agentos.AgentOsMaterialCreateRequest) gateway.lastPostBody;
        assertEquals(material, request.content());

        String getPath = "/ai/agentos/v2/materials/manifest%20001";
        gateway.getResponses.put(getPath, response(200, Map.of("manifestId", "manifest 001")));
        mockMvc.perform(get("/api/agentos/v2/materials/{manifestId}", "manifest 001"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.manifestId").value("manifest 001"));
        assertEquals(getPath, gateway.lastGetPath);
    }

    @Test
    void compositionResourceEndpointsCrossTheTrustedGateway() throws Exception {
        String usagePath = "/ai/agentos/v2/runs/run%20001/resource-usage";
        gateway.getResponses.put(usagePath, response(200, Map.of("runId", "run 001")));
        mockMvc.perform(get("/api/agentos/v2/runs/{runId}/resource-usage", "run 001"))
                .andExpect(status().isOk());
        assertEquals(usagePath, gateway.lastGetPath);

        String callsPath = usagePath + "/calls?stepId=report&cursor=20&pageSize=25";
        gateway.getResponses.put(callsPath, response(200, Map.of("items", List.of())));
        mockMvc.perform(get("/api/agentos/v2/runs/{runId}/resource-usage/calls", "run 001")
                        .param("stepId", "report")
                        .param("cursor", "20")
                        .param("pageSize", "25"))
                .andExpect(status().isOk());
        assertEquals(callsPath, gateway.lastGetPath);

        String fragmentsPath = "/ai/agentos/v2/runs/run%20001/artifacts/manifest%20001/fragments"
                + "?cursor=5&pageSize=10";
        gateway.getResponses.put(fragmentsPath, response(200, Map.of("items", List.of())));
        mockMvc.perform(get(
                        "/api/agentos/v2/runs/{runId}/artifacts/{manifestId}/fragments",
                        "run 001", "manifest 001"
                ).param("cursor", "5").param("pageSize", "10"))
                .andExpect(status().isOk());
        assertEquals(fragmentsPath, gateway.lastGetPath);
    }

    @Test
    void missionWorkspaceForwardsTheOptionalRunSelection() throws Exception {
        String workspacePath = "/ai/agentos/v2/missions/mission%20001/workspace?runId=run%20001";
        gateway.getResponses.put(workspacePath, response(200, Map.of(
                "missionId", "mission 001", "activeRun", Map.of("runId", "run 001")
        )));

        mockMvc.perform(get("/api/agentos/v2/missions/{missionId}/workspace", "mission 001")
                        .param("runId", "run 001"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.missionId").value("mission 001"));

        assertEquals(workspacePath, gateway.lastGetPath);
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

        gateway.getResponses.put("/ai/agentos/v2/runs/run_001/history-config", response(200, Map.of(
                "runId", "run_001", "input", Map.of("taskGoal", "Restore task")
        )));
        mockMvc.perform(get("/api/agentos/v2/runs/run_001/history-config"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.input.taskGoal").value("Restore task"));
        assertEquals("/ai/agentos/v2/runs/run_001/history-config", gateway.lastGetPath);

        gateway.getResponses.put("/ai/agentos/v2/runs/run%20001/execution-tree", response(200, Map.of(
                "run", Map.of("runId", "run 001"), "nodes", java.util.List.of()
        )));
        mockMvc.perform(get("/api/agentos/v2/runs/{runId}/execution-tree", "run 001"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.run.runId").value("run 001"));
        assertEquals("/ai/agentos/v2/runs/run%20001/execution-tree", gateway.lastGetPath);

        gateway.getResponses.put("/ai/agentos/v2/identity/health", response(503, Map.of(
                "detail", "identity query source unavailable"
        )));
        mockMvc.perform(get("/api/agentos/v2/identity/health"))
                .andExpect(status().isServiceUnavailable())
                .andExpect(jsonPath("$.detail").value("identity query source unavailable"));
        assertEquals("/ai/agentos/v2/identity/health", gateway.lastGetPath);

        mockMvc.perform(get("/api/agentos/core/workflows/runs/run_001/acg"))
                .andExpect(status().isNotFound());
    }

    @Test
    void listRunsForwardsTheCompleteHistoryFilterContract() throws Exception {
        String upstream = "/ai/agentos/v2/runs?statuses=running,waiting_review&domain=legal"
                + "&workflowId=workflow_1&missionId=mission_1&lifecyclePhase=review&source=acg"
                + "&sources=acg,chat&recordState=archived&summary=true&page=2&pageSize=50";
        gateway.getResponses.put(upstream, response(200, Map.of(
                "items", java.util.List.of(), "total", 0, "page", 2, "pageSize", 50
        )));

        mockMvc.perform(get("/api/agentos/v2/runs")
                        .param("statuses", "running,waiting_review")
                        .param("domain", "legal")
                        .param("workflowId", "workflow_1")
                        .param("missionId", "mission_1")
                        .param("lifecyclePhase", "review")
                        .param("source", "acg")
                        .param("sources", "acg,chat")
                        .param("recordState", "archived")
                        .param("summary", "true")
                        .param("page", "2")
                        .param("pageSize", "50"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total").value(0));

        assertEquals(upstream, gateway.lastGetPath);
    }

    @Test
    void missionRecordActionsUseEncodedMissionIdentity() throws Exception {
        String archivePath = "/ai/agentos/v2/missions/mission%20001/archive";
        gateway.postResponses.put(archivePath, response(200, Map.of("missionId", "mission 001", "recordState", "archived")));
        mockMvc.perform(post("/api/agentos/v2/missions/{missionId}/archive", "mission 001"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.recordState").value("archived"));
        assertEquals(archivePath, gateway.lastPostPath);

        String deletePath = "/ai/agentos/v2/missions/mission%20001";
        gateway.deleteResponses.put(deletePath, response(200, Map.of("missionId", "mission 001", "recordState", "deleted")));
        mockMvc.perform(delete("/api/agentos/v2/missions/{missionId}", "mission 001"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.recordState").value("deleted"));
        assertEquals(deletePath, gateway.lastDeletePath);
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

    @Test
    void runCancellationForwardsOwnedRunSubresourceAndKeepsConflictStatus() throws Exception {
        String cancelPath = "/ai/agentos/v2/runs/run%20001/cancel";
        gateway.postResponses.put(cancelPath, response(200, Map.of("runId", "run_001", "status", "cancelled")));
        mockMvc.perform(post("/api/agentos/v2/runs/{runId}/cancel", "run 001"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("cancelled"));
        assertEquals("/ai/agentos/v2/runs/run%20001/cancel", gateway.lastPostPath);

        String conflictPath = "/ai/agentos/v2/runs/run_002/cancel";
        gateway.postResponses.put(conflictPath, response(409, Map.of("detail", "run cannot be cancelled")));
        mockMvc.perform(post("/api/agentos/v2/runs/{runId}/cancel", "run_002"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.detail").value("run cannot be cancelled"));
        assertEquals(conflictPath, gateway.lastPostPath);
    }

    private static Map<String, Object> response(int status, Map<String, Object> body) {
        Map<String, Object> result = new LinkedHashMap<>(body);
        result.put(AgentOsGatewayService.INTERNAL_HTTP_STATUS_KEY, status);
        return result;
    }

    private static final class RecordingGateway extends AgentOsGatewayService {
        private final Map<String, Map<String, Object>> getResponses = new HashMap<>();
        private final Map<String, Map<String, Object>> postResponses = new HashMap<>();
        private final Map<String, Map<String, Object>> deleteResponses = new HashMap<>();
        private String lastGetPath;
        private String lastPostPath;
        private Object lastPostBody;
        private String lastDeletePath;

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


        @Override
        public Map<String, Object> delete(String path) {
            lastDeletePath = path;
            return deleteResponses.getOrDefault(path, response(404, Map.of("message", "not found")));
        }
    }
}
