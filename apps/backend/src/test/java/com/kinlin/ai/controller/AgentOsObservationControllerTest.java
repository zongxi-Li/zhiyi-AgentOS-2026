package com.kinlin.ai.controller;

import com.kinlin.ai.exception.AgentOsGatewayExceptionHandler;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
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
    void missionWorkspaceForwardsTheOptionalRunSelection() throws Exception {
        String workspacePath = "/ai/agentos/v2/missions/mission%20001/workspace?runId=run%20001";
        gateway.getResponses.put(workspacePath, RecordingAgentOsGateway.response(200, Map.of(
                "missionId", "mission 001", "activeRun", Map.of("runId", "run 001")
        )));

        mockMvc.perform(get("/api/agentos/v2/missions/{missionId}/workspace", "mission 001")
                        .param("runId", "run 001"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.missionId").value("mission 001"));

        assertEquals(workspacePath, gateway.lastGetPath);
    }

    @Test
    void runObservationQueriesPreserveUpstreamStatusesAndBodies() throws Exception {
        String usagePath = "/ai/agentos/v2/runs/run%20001/resource-usage";
        gateway.getResponses.put(usagePath, RecordingAgentOsGateway.response(200, Map.of("runId", "run 001")));
        mockMvc.perform(get("/api/agentos/v2/runs/{runId}/resource-usage", "run 001"))
                .andExpect(status().isOk());
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
                "runId", "run_001", "nodes", List.of())));
        mockMvc.perform(get("/api/agentos/v2/runs/{runId}/graph", "run_001"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.runId").value("run_001"));
        assertEquals(graphPath, gateway.lastGetPath);

        String treePath = "/ai/agentos/v2/runs/run%20001/execution-tree";
        gateway.getResponses.put(treePath, RecordingAgentOsGateway.response(200, Map.of(
                "run", Map.of("runId", "run 001"), "nodes", List.of())));
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
