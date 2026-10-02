package com.kinlin.ai.controller;

import com.kinlin.ai.exception.AgentOsGatewayExceptionHandler;
import com.kinlin.ai.projection.resource.ResourceUsageQueryFixture;
import com.kinlin.ai.projection.workspace.WorkspaceQueryFixture;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * OBSERVATION ownership: workspace, history-config, graph, execution tree,
 * resource usage, trace, memory events, provenance, checkpoints, identity health.
 */
class AgentOsObservationControllerTest {

    private MockMvc mockMvc;
    private RecordingAgentOsGateway gateway;

    @BeforeEach
    void setUp() {
        gateway = new RecordingAgentOsGateway();
        mockMvc = MockMvcBuilders.standaloneSetup(new AgentOsObservationController(gateway))
                .setControllerAdvice(new AgentOsGatewayExceptionHandler())
                .build();
    }

    @Test
    void missionWorkspaceForwardsTheOptionalRunSelectionAndProjectsTheEnvelope() throws Exception {
        String workspacePath = "/ai/agentos/v2/missions/mission%20001/workspace?runId=run%20001";
        gateway.getResponses.put(workspacePath, RecordingAgentOsGateway.response(
                200, WorkspaceQueryFixture.normalPlan()));

        String body = mockMvc.perform(get("/api/agentos/v2/missions/{missionId}/workspace", "mission 001")
                        .param("runId", "run 001"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.mission.missionId").value("mission_1"))
                .andExpect(jsonPath("$.activeGraph.taskPlanVersion").value(2))
                .andExpect(jsonPath("$.entries[0].entryId").value("folder:overview"))
                .andExpect(jsonPath("$..userId").doesNotExist())
                .andExpect(jsonPath("$..identityVersion").doesNotExist())
                .andExpect(jsonPath("$._httpStatus").doesNotExist())
                .andReturn().getResponse().getContentAsString();
        assertFalse(body.contains(WorkspaceQueryFixture.SECRET));
        assertEquals(workspacePath, gateway.lastGetPath);
    }

    @Test
    void missionWorkspaceKeepsErrorStatusesAndFailsContractViolationsWithoutEcho() throws Exception {
        gateway.getResponses.put("/ai/agentos/v2/missions/m404/workspace",
                RecordingAgentOsGateway.response(404, Map.of(
                        "code", "AGENTOS_REQUEST_REJECTED", "message", "not found", "requestId", "request-1")));
        mockMvc.perform(get("/api/agentos/v2/missions/{missionId}/workspace", "m404"))
                .andExpect(status().isNotFound())
                .andExpect(content().json(
                        "{\"code\":\"AGENTOS_REQUEST_REJECTED\",\"message\":\"not found\",\"requestId\":\"request-1\"}", true));

        gateway.getResponses.put("/ai/agentos/v2/missions/mBad/workspace",
                RecordingAgentOsGateway.response(200, Map.of("missionId", WorkspaceQueryFixture.SECRET)));
        String body = mockMvc.perform(get("/api/agentos/v2/missions/{missionId}/workspace", "mBad"))
                .andExpect(status().isBadGateway())
                .andExpect(jsonPath("$.code").value("AGENTOS_CONTRACT_INVALID"))
                .andExpect(jsonPath("$._httpStatus").doesNotExist())
                .andReturn().getResponse().getContentAsString();
        assertFalse(body.contains(WorkspaceQueryFixture.SECRET));
    }

    @Test
    void resourceUsageKeepsErrorStatusesAndFailsContractViolationsWithoutEcho() throws Exception {
        gateway.getResponses.put("/ai/agentos/v2/runs/run_404/resource-usage",
                RecordingAgentOsGateway.response(404, Map.of(
                        "code", "AGENTOS_NOT_FOUND", "message", "run not found", "requestId", "request-2")));
        mockMvc.perform(get("/api/agentos/v2/runs/{runId}/resource-usage", "run_404"))
                .andExpect(status().isNotFound())
                .andExpect(content().json(
                        "{\"code\":\"AGENTOS_NOT_FOUND\",\"message\":\"run not found\",\"requestId\":\"request-2\"}", true));

        // A wire without the required usage object must 502 instead of fabricating empty data.
        Map<String, Object> missingUsage = ResourceUsageQueryFixture.observedUsage();
        missingUsage.remove("usage");
        gateway.getResponses.put("/ai/agentos/v2/runs/run_bad/resource-usage",
                RecordingAgentOsGateway.response(200, missingUsage));
        String body = mockMvc.perform(get("/api/agentos/v2/runs/{runId}/resource-usage", "run_bad"))
                .andExpect(status().isBadGateway())
                .andExpect(jsonPath("$.code").value("AGENTOS_CONTRACT_INVALID"))
                .andReturn().getResponse().getContentAsString();
        assertFalse(body.contains(ResourceUsageQueryFixture.SECRET));
    }

    @Test
    void missionWorkspaceKeepsUsableProjectionsWithTheirDiagnostics() throws Exception {
        gateway.getResponses.put("/ai/agentos/v2/missions/mDeferred/workspace",
                RecordingAgentOsGateway.response(200, WorkspaceQueryFixture.deferredFallback()));
        mockMvc.perform(get("/api/agentos/v2/missions/{missionId}/workspace", "mDeferred"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.diagnostics[0].code").value("PLANNING_PROJECTION_PENDING"))
                .andExpect(jsonPath("$.diagnostics[0].details.runtimeStatus").value("running"))
                .andExpect(jsonPath("$.diagnostics[0].details.errorCode").doesNotExist())
                .andExpect(jsonPath("$.activeRun.status").value("running"));

        gateway.getResponses.put("/ai/agentos/v2/missions/mNoPlan/workspace",
                RecordingAgentOsGateway.response(200, WorkspaceQueryFixture.noPlan()));
        mockMvc.perform(get("/api/agentos/v2/missions/{missionId}/workspace", "mNoPlan"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.diagnostics[0].code").value("PLAN_SNAPSHOT_UNRESOLVED"))
                .andExpect(jsonPath("$.diagnostics[0].details.runId").value("run_1"))
                .andExpect(jsonPath("$.diagnostics[0].details.taskPlanVersion").doesNotExist())
                .andExpect(jsonPath("$.entries[0].entryId").value("folder:overview"));
    }

    @Test
    void runObservationQueriesPreserveUpstreamStatusesAndBodies() throws Exception {
        String usagePath = "/ai/agentos/v2/runs/run%20001/resource-usage";
        gateway.getResponses.put(usagePath, RecordingAgentOsGateway.response(
                200, ResourceUsageQueryFixture.observedUsage()));
        String usageBody = mockMvc.perform(get("/api/agentos/v2/runs/{runId}/resource-usage", "run 001"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.usage.callCount").value(2))
                .andExpect(jsonPath("$.contextPressure.source").value("usage_derived"))
                .andExpect(jsonPath("$.scheduler").doesNotExist())
                .andExpect(jsonPath("$..features").doesNotExist())
                .andReturn().getResponse().getContentAsString();
        assertFalse(usageBody.contains(ResourceUsageQueryFixture.SECRET));
        assertEquals(usagePath, gateway.lastGetPath);

        String callsPath = usagePath + "/calls?stepId=report&cursor=20&pageSize=25";
        gateway.getResponses.put(callsPath, RecordingAgentOsGateway.response(200, Map.of("items", List.of())));
        mockMvc.perform(get("/api/agentos/v2/runs/{runId}/resource-usage/calls", "run 001")
                        .param("stepId", "report")
                        .param("cursor", "20")
                        .param("pageSize", "25"))
                .andExpect(status().isOk());
        assertEquals(callsPath, gateway.lastGetPath);

        String graphPath = "/ai/agentos/v2/runs/run_001/graph";
        gateway.getResponses.put(graphPath, RecordingAgentOsGateway.response(200, Map.of(
                "runId", "run_001", "nodes", List.of(Map.of("nodeId", "n", "metadata", Map.of("taskId", "t", "scheduler", "secret"))),
                "compiledPackage", Map.of("secret", "secret"))));
        mockMvc.perform(get("/api/agentos/v2/runs/{runId}/graph", "run_001"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.runId").value("run_001"))
                .andExpect(jsonPath("$.nodes[0].display.taskId").value("t"))
                .andExpect(jsonPath("$.nodes[0].metadata").doesNotExist())
                .andExpect(jsonPath("$.compiledPackage").doesNotExist());
        assertEquals(graphPath, gateway.lastGetPath);

        String treePath = "/ai/agentos/v2/runs/run%20001/execution-tree";
        gateway.getResponses.put(treePath, RecordingAgentOsGateway.response(200, Map.of(
                "run", Map.of("runId", "run 001", "graphVersion", 1), "nodes", List.of(),
                "blueprint", Map.of("graph", Map.of("nodes", List.of(), "edges", List.of())))));
        mockMvc.perform(get("/api/agentos/v2/runs/{runId}/execution-tree", "run 001"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.run.runId").value("run 001"));
        assertEquals(treePath, gateway.lastGetPath);

        String historyPath = "/ai/agentos/v2/runs/run_001/history-config";
        gateway.getResponses.put(historyPath, RecordingAgentOsGateway.response(200, Map.of(
                "runId", "run_001", "input", Map.of("taskGoal", "Restore task"))));
        mockMvc.perform(get("/api/agentos/v2/runs/{runId}/history-config", "run_001"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.input.taskGoal").value("Restore task"));
        assertEquals(historyPath, gateway.lastGetPath);
    }

    @Test
    void identityHealthPassesTheUpstreamFailureThrough() throws Exception {
        gateway.getResponses.put("/ai/agentos/v2/identity/health", RecordingAgentOsGateway.response(503, Map.of(
                "detail", "identity query source unavailable"
        )));
        mockMvc.perform(get("/api/agentos/v2/identity/health"))
                .andExpect(status().isServiceUnavailable())
                .andExpect(jsonPath("$.detail").value("identity query source unavailable"));
        assertEquals("/ai/agentos/v2/identity/health", gateway.lastGetPath);
    }

    @Test
    void traceForwardsWorkspaceViewAndKeepsDefaultFullExport() throws Exception {
        String path = "/ai/agentos/v2/runs/run_001/trace";
        gateway.getResponses.put(path, RecordingAgentOsGateway.response(200, Map.of("eventCount", 50000)));
        gateway.getResponses.put(path + "?view=workspace", RecordingAgentOsGateway.response(200, Map.of("eventCount", 50000)));
        mockMvc.perform(get("/api/agentos/v2/runs/{runId}/trace", "run_001").param("view", "workspace"))
                .andExpect(status().isOk());
        assertEquals(path + "?view=workspace", gateway.lastGetPath);
        mockMvc.perform(get("/api/agentos/v2/runs/{runId}/trace", "run_001"))
                .andExpect(status().isOk());
        assertEquals(path, gateway.lastGetPath);
    }

    @Test
    void memoryProvenanceAndCheckpointQueriesUseOwnedSubresourcePaths() throws Exception {
        String memoryPath = "/ai/agentos/v2/runs/run_001/memory-events";
        gateway.getResponses.put(memoryPath, RecordingAgentOsGateway.response(200, Map.of("events", List.of())));
        mockMvc.perform(get("/api/agentos/v2/runs/{runId}/memory-events", "run_001"))
                .andExpect(status().isOk());
        assertEquals(memoryPath, gateway.lastGetPath);

        String provenancePath = "/ai/agentos/v2/runs/run_001/provenance";
        gateway.getResponses.put(provenancePath, RecordingAgentOsGateway.response(200, Map.of(
                "runId", "run_001", "sources", List.of())));
        mockMvc.perform(get("/api/agentos/v2/runs/{runId}/provenance", "run_001"))
                .andExpect(status().isOk());
        assertEquals(provenancePath, gateway.lastGetPath);

        String checkpointPath = "/ai/agentos/v2/runs/run_001/checkpoints";
        gateway.getResponses.put(checkpointPath, RecordingAgentOsGateway.response(200, Map.of("items", List.of())));
        mockMvc.perform(get("/api/agentos/v2/runs/{runId}/checkpoints", "run_001"))
                .andExpect(status().isOk());
        assertEquals(checkpointPath, gateway.lastGetPath);
    }
}
