package com.kinlin.ai.controller;

import com.kinlin.ai.exception.AgentOsGatewayExceptionHandler;
import com.kinlin.ai.gateway.AiSseGatewayService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.util.List;
import java.util.Map;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.asyncDispatch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.request;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Route compatibility of the J1.2B controller split: the six ownership controllers
 * registered together must resolve the whole former /api/agentos/v2 route set with
 * no ambiguous mapping (a duplicate mapping would fail context construction), and
 * the retired legacy route must stay absent.
 */
class AgentOsRouteCompatibilityTest {

    private RecordingAgentOsGateway gateway;
    private AiSseGatewayService sseGateway;
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        gateway = new RecordingAgentOsGateway();
        sseGateway = mock(AiSseGatewayService.class);
        mockMvc = controllers(sseGateway);
    }

    private MockMvc controllers(AiSseGatewayService sse) {
        return MockMvcBuilders.standaloneSetup(
                        new AgentOsMissionController(gateway),
                        new AgentOsRunController(gateway),
                        new AgentOsReviewController(gateway),
                        new AgentOsArtifactController(gateway),
                        new AgentOsObservationController(gateway),
                        new AgentOsEventController(sse))
                .setControllerAdvice(new AgentOsGatewayExceptionHandler())
                .build();
    }

    @Test
    void theSplitControllersJointlyResolveTheFormerRouteSet() throws Exception {
        gateway.getResponses.put("/ai/agentos/v2/runs/run_1", RecordingAgentOsGateway.response(200, Map.of(
                "runId", "run_1", "status", "running")));
        mockMvc.perform(get("/api/agentos/v2/runs/{runId}", "run_1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.runId").value("run_1"));

        gateway.postResponses.put("/ai/agentos/v2/missions/m1/archive", RecordingAgentOsGateway.response(200, Map.of(
                "recordState", "archived")));
        mockMvc.perform(post("/api/agentos/v2/missions/{missionId}/archive", "m1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.recordState").value("archived"));

        gateway.postResponses.put("/ai/agentos/v2/runs/run_1/cancel", RecordingAgentOsGateway.response(200, Map.of(
                "status", "cancelled")));
        mockMvc.perform(post("/api/agentos/v2/runs/{runId}/cancel", "run_1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("cancelled"));

        gateway.getResponses.put("/ai/agentos/v2/runs/run_1/reviews", RecordingAgentOsGateway.response(200, Map.of(
                "items", List.of())));
        mockMvc.perform(get("/api/agentos/v2/runs/{runId}/reviews", "run_1"))
                .andExpect(status().isOk());

        gateway.getResponses.put("/ai/agentos/v2/runs/run_1/artifacts", RecordingAgentOsGateway.response(200, Map.of(
                "runId", "run_1", "items", List.of(), "total", 0)));
        mockMvc.perform(get("/api/agentos/v2/runs/{runId}/artifacts", "run_1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.runId").value("run_1"));

        gateway.getResponses.put("/ai/agentos/v2/materials/m1", RecordingAgentOsGateway.response(200, Map.of(
                "manifestId", "m1")));
        mockMvc.perform(get("/api/agentos/v2/materials/{manifestId}", "m1"))
                .andExpect(status().isOk());

        gateway.getResponses.put("/ai/agentos/v2/runs/run_1/trace", RecordingAgentOsGateway.response(200, Map.of(
                "runId", "run_1", "missionId", "m1", "workflowId", "wf", "domain", "general",
                "status", "running", "eventCount", 1, "events", List.of())));
        mockMvc.perform(get("/api/agentos/v2/runs/{runId}/trace", "run_1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.runId").value("run_1"))
                .andExpect(jsonPath("$.eventCount").value(1));

        gateway.getResponses.put("/ai/agentos/v2/identity/health", RecordingAgentOsGateway.response(200, Map.of(
                "status", "healthy", "source", "agentos-v2", "backlogCount", 0, "failedCount", 0,
                "unappliedEventCount", 0, "inboxBacklog", 0, "outboxBacklog", 0,
                "startupReconciliation", Map.of("examinedMissions", 0, "examinedRuns", 0,
                        "repairedMissions", 0, "repairedRuns", 0, "replayedEvents", 0, "failureCount", 0))));
        mockMvc.perform(get("/api/agentos/v2/identity/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("healthy"));
    }

    @Test
    void theRetiredLegacyRuntimeRouteStaysAbsent() throws Exception {
        mockMvc.perform(get("/api/agentos/core/workflows/runs/{runId}/acg", "run_1"))
                .andExpect(status().isNotFound());
    }

    @Test
    void sseEntryResolvesWhenAllControllersShareTheContext() throws Exception {
        when(sseGateway.openGet("/ai/agentos/v2/runs/run_1/events")).thenReturn(Mono.just(
                ResponseEntity.ok().contentType(MediaType.TEXT_EVENT_STREAM).body(Flux.empty())));

        MvcResult started = mockMvc.perform(get("/api/agentos/v2/runs/{runId}/events", "run_1"))
                .andExpect(request().asyncStarted())
                .andReturn();
        mockMvc.perform(asyncDispatch(started))
                .andExpect(status().isOk());
    }
}
