package com.kinlin.ai.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.config.AgentProperties;
import com.kinlin.ai.dto.agentos.AgentOsMissionCreateRequest;
import com.kinlin.ai.dto.agentos.AgentOsMissionRunCreateRequest;
import com.kinlin.ai.dto.agentos.AgentOsApiResponse;
import com.kinlin.ai.dto.agentos.AgentOsErrorResponse;
import com.kinlin.ai.service.AgentOsGatewayService;
import com.kinlin.ai.exception.AgentOsGatewayExceptionHandler;
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
        mockMvc = MockMvcBuilders.standaloneSetup(new AgentOsGatewayController(gateway))
                .setControllerAdvice(new AgentOsGatewayExceptionHandler())
                .build();
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
    void createMissionRunPostsTheExactContractAndPreservesUpstreamStatus() throws Exception {
        String upstream = "/ai/agentos/v2/missions/mission%20001/runs";
        gateway.postResponses.put(upstream, response(202, Map.of(
                "missionId", "mission 001", "runId", "run_002", "status", "pending"
        )));

        mockMvc.perform(post("/api/agentos/v2/missions/{missionId}/runs", "mission 001")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of(
                                "workflowId", "workflow_1",
                                "reviewMode", "auto",
                                "input", Map.of("taskGoal", "再次执行"),
                                "enabledPluginIds", List.of("plugin_1"),
                                "clientRequestId", "rerun-request-1",
                                "sourceRunId", "run_001",
                                "rerunReason", "manual_rerun"
                        ))))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.runId").value("run_002"));

        assertEquals(upstream, gateway.lastPostPath);
        AgentOsMissionRunCreateRequest request = (AgentOsMissionRunCreateRequest) gateway.lastPostBody;
        assertEquals("run_001", request.sourceRunId());
        assertEquals("manual_rerun", request.rerunReason());
        assertEquals("再次执行", request.input().get("taskGoal"));
        assertEquals(List.of("plugin_1"), request.enabledPluginIds());
    }

    @Test
    void resourcesAreStraightProxiesWithoutLegacyRuntimeGraphEndpoints() throws Exception {
        gateway.getResponses.put("/ai/agentos/v2/resources", response(200, Map.of(
                "items", java.util.List.of(), "total", 0
        )));
        mockMvc.perform(get("/api/agentos/v2/resources"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total").value(0));
        assertEquals("/ai/agentos/v2/resources", gateway.lastGetPath);

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
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.code").value("AGENTOS_VALIDATION_ERROR"));
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
                .andExpect(jsonPath("$.code").value("AGENTOS_REQUEST_REJECTED"))
                .andExpect(jsonPath("$.message").value("run cannot be cancelled"));
        assertEquals(conflictPath, gateway.lastPostPath);
    }

    @Test
    void failedStepRetryForwardsRunStepAndPreservesAcceptedStatus() throws Exception {
        String retryPath = "/ai/agentos/v2/runs/run%20001/steps/design%20step/retry";
        gateway.postResponses.put(retryPath, response(202, Map.of(
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

    @Test
    void traceForwardsWorkspaceViewAndKeepsDefaultFullExport() throws Exception {
        String path = "/ai/agentos/v2/runs/run_001/trace";
        gateway.getResponses.put(path, response(200, Map.of("eventCount", 50000)));
        gateway.getResponses.put(path + "?view=workspace", response(200, Map.of("eventCount", 50000)));
        mockMvc.perform(get("/api/agentos/v2/runs/run_001/trace").param("view", "workspace"))
                .andExpect(status().isOk());
        assertEquals(path + "?view=workspace", gateway.lastGetPath);
        mockMvc.perform(get("/api/agentos/v2/runs/run_001/trace"))
                .andExpect(status().isOk());
        assertEquals(path, gateway.lastGetPath);
    }

    private static Map<String, Object> response(int status, Map<String, Object> body) {
        Map<String, Object> result = new LinkedHashMap<>(body);
        result.put(AgentOsGatewayService.INTERNAL_HTTP_STATUS_KEY, status);
        return result;
    }

    private static final class RecordingGateway extends AgentOsGatewayService {
        private final ObjectMapper mapper = new ObjectMapper().findAndRegisterModules();
        private final Map<String, Map<String, Object>> getResponses = new HashMap<>();
        private final Map<String, Map<String, Object>> postResponses = new HashMap<>();
        private final Map<String, Map<String, Object>> deleteResponses = new HashMap<>();
        private String lastGetPath;
        private String lastPostPath;
        private Object lastPostBody;
        private String lastDeletePath;

        private RecordingGateway() {
            super(WebClient.builder().baseUrl("http://localhost:8000").build(), new AgentProperties());
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
        public <T extends AgentOsApiResponse> TypedResponse<T> postTyped(
                String path, Object body, Class<T> responseType
        ) {
            lastPostPath = path;
            lastPostBody = body;
            Map<String, Object> configured = postResponses.getOrDefault(
                    path, response(404, Map.of("code", "NOT_FOUND", "message", "not found"))
            );
            int status = ((Number) configured.get(INTERNAL_HTTP_STATUS_KEY)).intValue();
            if (status < 200 || status >= 300) {
                return new TypedResponse<>(status, null, new AgentOsErrorResponse(
                        String.valueOf(configured.getOrDefault("code", "AGENTOS_REQUEST_REJECTED")),
                        String.valueOf(configured.getOrDefault("message", configured.getOrDefault(
                                "detail", "AgentOS request was rejected (HTTP " + status + ")."))),
                        configured.get("requestId") instanceof String value ? value : null
                ));
            }
            Map<String, Object> canonical = new LinkedHashMap<>();
            canonical.put("runId", configured.getOrDefault("runId", "run_001"));
            canonical.put("missionId", configured.getOrDefault("missionId", "mission_001"));
            canonical.put("workflowId", configured.getOrDefault("workflowId", "workflow_001"));
            canonical.put("status", configured.getOrDefault("status", "pending"));
            canonical.put("lifecyclePhase", configured.getOrDefault("lifecyclePhase", "planning"));
            canonical.put("runtimeRevision", configured.getOrDefault("runtimeRevision", 0));
            canonical.put("createdAt", configured.getOrDefault("createdAt", "2026-09-27T12:00:00Z"));
            canonical.put("updatedAt", configured.getOrDefault("updatedAt", "2026-09-27T12:00:00Z"));
            if (responseType.getSimpleName().equals("AgentOsReviewResponse")) {
                canonical.put("operationId", configured.getOrDefault("operationId", "op-1"));
                canonical.put("decision", configured.getOrDefault("decision", "approved"));
            }
            if (responseType.getSimpleName().equals("AgentOsOperationResponse")) {
                canonical.put("operation", configured.getOrDefault("operation", "cancel"));
            }
            return new TypedResponse<>(status, mapper.convertValue(canonical, responseType), null);
        }


        @Override
        public Map<String, Object> delete(String path) {
            lastDeletePath = path;
            return deleteResponses.getOrDefault(path, response(404, Map.of("message", "not found")));
        }
    }
}
