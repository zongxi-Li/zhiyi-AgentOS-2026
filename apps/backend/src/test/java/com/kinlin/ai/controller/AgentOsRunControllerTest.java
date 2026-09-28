package com.kinlin.ai.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.dto.agentos.AgentOsMissionRunCreateRequest;
import com.kinlin.ai.exception.AgentOsGatewayExceptionHandler;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/** RUN ownership: mission-nested create, history filter list, read, cancel. */
class AgentOsRunControllerTest {

    private MockMvc mockMvc;
    private ObjectMapper objectMapper;
    private RecordingAgentOsGateway gateway;

    @BeforeEach
    void setUp() {
        objectMapper = new ObjectMapper();
        gateway = new RecordingAgentOsGateway();
        mockMvc = MockMvcBuilders.standaloneSetup(new AgentOsRunController(gateway))
                .setControllerAdvice(new AgentOsGatewayExceptionHandler())
                .build();
    }

    @Test
    void createMissionRunPostsTheExactContractAndPreservesUpstreamStatus() throws Exception {
        String upstream = "/ai/agentos/v2/missions/mission%20001/runs";
        gateway.postResponses.put(upstream, RecordingAgentOsGateway.response(202, Map.of(
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
    void listRunsForwardsTheCompleteHistoryFilterContract() throws Exception {
        String upstream = "/ai/agentos/v2/runs?statuses=running,waiting_review&domain=legal"
                + "&workflowId=workflow_1&missionId=mission_1&lifecyclePhase=review&source=acg"
                + "&sources=acg,chat&recordState=archived&summary=true&page=2&pageSize=50";
        gateway.getResponses.put(upstream, RecordingAgentOsGateway.response(200, Map.of(
                "items", List.of(), "total", 0, "page", 2, "pageSize", 50
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
    void getRunUsesEncodedRunIdentity() throws Exception {
        String path = "/ai/agentos/v2/runs/run%20001";
        gateway.getResponses.put(path, RecordingAgentOsGateway.response(200, Map.of(
                "runId", "run 001", "status", "running"
        )));

        mockMvc.perform(get("/api/agentos/v2/runs/{runId}", "run 001"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("running"));

        assertEquals(path, gateway.lastGetPath);
    }

    @Test
    void runCancellationForwardsOwnedRunSubresourceAndKeepsConflictStatus() throws Exception {
        String cancelPath = "/ai/agentos/v2/runs/run%20001/cancel";
        gateway.postResponses.put(cancelPath, RecordingAgentOsGateway.response(200, Map.of(
                "runId", "run_001", "status", "cancelled")));
        mockMvc.perform(post("/api/agentos/v2/runs/{runId}/cancel", "run 001"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("cancelled"));
        assertEquals("/ai/agentos/v2/runs/run%20001/cancel", gateway.lastPostPath);

        String conflictPath = "/ai/agentos/v2/runs/run_002/cancel";
        gateway.postResponses.put(conflictPath, RecordingAgentOsGateway.response(409, new LinkedHashMap<>(Map.of(
                "detail", "run cannot be cancelled"))));
        mockMvc.perform(post("/api/agentos/v2/runs/{runId}/cancel", "run_002"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("AGENTOS_REQUEST_REJECTED"))
                .andExpect(jsonPath("$.message").value("run cannot be cancelled"));
        assertEquals(conflictPath, gateway.lastPostPath);
    }
}
