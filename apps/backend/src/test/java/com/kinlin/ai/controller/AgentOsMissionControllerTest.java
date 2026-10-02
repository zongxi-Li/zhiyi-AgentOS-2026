package com.kinlin.ai.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.dto.agentos.AgentOsMissionCreateRequest;
import com.kinlin.ai.exception.AgentOsGatewayExceptionHandler;
import com.kinlin.ai.projection.mission.MissionQueryFixture;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/** MISSION ownership: create / list / read / archive / restore / delete. */
class AgentOsMissionControllerTest {

    private MockMvc mockMvc;
    private ObjectMapper objectMapper;
    private RecordingAgentOsGateway gateway;

    @BeforeEach
    void setUp() {
        objectMapper = new ObjectMapper();
        gateway = new RecordingAgentOsGateway();
        mockMvc = MockMvcBuilders.standaloneSetup(new AgentOsMissionController(gateway))
                .setControllerAdvice(new AgentOsGatewayExceptionHandler())
                .build();
    }

    @Test
    void createMissionForwardsOnlyTheV2ContractAndPreservesAccepted() throws Exception {
        gateway.postResponses.put("/ai/agentos/v2/missions", RecordingAgentOsGateway.response(202, Map.of(
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
    void createMissionRejectsContractViolationsWithTheStableEnvelope() throws Exception {
        mockMvc.perform(post("/api/agentos/v2/missions")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.code").value("AGENTOS_VALIDATION_ERROR"));
    }

    @Test
    void listMissionsForwardsDefaultPaginationWithoutEmptyFilters() throws Exception {
        String path = "/ai/agentos/v2/missions?page=1&pageSize=20";
        gateway.getResponses.put(path, RecordingAgentOsGateway.response(200, Map.of(
                "items", List.of(), "total", 0
        )));

        mockMvc.perform(get("/api/agentos/v2/missions"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total").value(0));

        assertEquals(path, gateway.lastGetPath);
    }

    @Test
    void listMissionsForwardsTheStatusFilter() throws Exception {
        String path = "/ai/agentos/v2/missions?status=archived&page=2&pageSize=50";
        gateway.getResponses.put(path, RecordingAgentOsGateway.response(200, Map.of("total", 0)));

        mockMvc.perform(get("/api/agentos/v2/missions")
                        .param("status", "archived").param("page", "2").param("pageSize", "50"))
                .andExpect(status().isOk());

        assertEquals(path, gateway.lastGetPath);
    }

    @Test
    void missionReadsUseEncodedMissionIdentity() throws Exception {
        String getPath = "/ai/agentos/v2/missions/mission%20001";
        gateway.getResponses.put(getPath, RecordingAgentOsGateway.response(200, MissionQueryFixture.detail()));
        mockMvc.perform(get("/api/agentos/v2/missions/{missionId}", "mission 001"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.mission.missionId").value("mission_1"));
        assertEquals(getPath, gateway.lastGetPath);

        String runsPath = "/ai/agentos/v2/missions/mission%20001/runs";
        gateway.getResponses.put(runsPath, RecordingAgentOsGateway.response(200, MissionQueryFixture.history()));
        mockMvc.perform(get("/api/agentos/v2/missions/{missionId}/runs", "mission 001"))
                .andExpect(status().isOk());
        assertEquals(runsPath, gateway.lastGetPath);
    }

    @Test
    void missionRecordActionsUseEncodedMissionIdentity() throws Exception {
        String archivePath = "/ai/agentos/v2/missions/mission%20001/archive";
        gateway.postResponses.put(archivePath, RecordingAgentOsGateway.response(200, Map.of(
                "missionId", "mission 001", "recordState", "archived")));
        mockMvc.perform(post("/api/agentos/v2/missions/{missionId}/archive", "mission 001"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.recordState").value("archived"));
        assertEquals(archivePath, gateway.lastPostPath);

        String restorePath = "/ai/agentos/v2/missions/mission%20001/restore";
        gateway.postResponses.put(restorePath, RecordingAgentOsGateway.response(200, Map.of(
                "missionId", "mission 001", "recordState", "active")));
        mockMvc.perform(post("/api/agentos/v2/missions/{missionId}/restore", "mission 001"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.recordState").value("active"));
        assertEquals(restorePath, gateway.lastPostPath);

        String deletePath = "/ai/agentos/v2/missions/mission%20001";
        gateway.deleteResponses.put(deletePath, RecordingAgentOsGateway.response(200, Map.of(
                "missionId", "mission 001", "recordState", "deleted")));
        mockMvc.perform(delete("/api/agentos/v2/missions/{missionId}", "mission 001"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.recordState").value("deleted"));
        assertEquals(deletePath, gateway.lastDeletePath);
    }

    @Test
    void missionArchiveRejectsBlankBodyShapesOnlyThroughTheGateway() throws Exception {
        // 4xx envelope from the gateway keeps code/message projection.
        gateway.postResponses.put("/ai/agentos/v2/missions/mission_001/archive",
                RecordingAgentOsGateway.response(409, new LinkedHashMap<>(Map.of(
                        "code", "AGENTOS_CONFLICT", "message", "already archived"))));
        mockMvc.perform(post("/api/agentos/v2/missions/{missionId}/archive", "mission_001"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("AGENTOS_CONFLICT"))
                .andExpect(jsonPath("$._httpStatus").doesNotExist());
        assertTrue(gateway.lastPostBody instanceof Map);
    }
}
