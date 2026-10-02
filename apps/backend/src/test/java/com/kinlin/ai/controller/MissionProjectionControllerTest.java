package com.kinlin.ai.controller;

import com.kinlin.ai.exception.AgentOsGatewayExceptionHandler;
import com.kinlin.ai.projection.common.dto.QueryError;
import com.kinlin.ai.projection.mission.MissionQueryFixture;
import com.kinlin.ai.projection.mission.dto.MissionDetailQuery;
import com.kinlin.ai.projection.mission.dto.MissionListQuery;
import com.kinlin.ai.projection.mission.dto.MissionRunHistoryQuery;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import java.util.List;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class MissionProjectionControllerTest {
    private RecordingAgentOsGateway gateway;
    private AgentOsMissionController controller;
    private MockMvc mvc;

    @BeforeEach
    void setup() {
        gateway = new RecordingAgentOsGateway();
        controller = new AgentOsMissionController(gateway);
        mvc = MockMvcBuilders.standaloneSetup(controller).setControllerAdvice(new AgentOsGatewayExceptionHandler()).build();
    }

    @Test
    void readsReturnProjectionTypesAndIgnoreInternalFieldsAtEveryDepth() throws Exception {
        gateway.getResponses.put("/ai/agentos/v2/missions/mission_1", RecordingAgentOsGateway.response(200, MissionQueryFixture.detail()));
        gateway.getResponses.put("/ai/agentos/v2/missions/mission_1/runs", RecordingAgentOsGateway.response(200, MissionQueryFixture.history()));
        assertInstanceOf(MissionDetailQuery.class, controller.getMission("mission_1").getBody());
        assertInstanceOf(MissionRunHistoryQuery.class, controller.getMissionRuns("mission_1").getBody());
        mvc.perform(get("/api/agentos/v2/missions/mission_1"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.mission.goal").value("审核合同"))
                .andExpect(jsonPath("$.graphs[0].version").value(3))
                .andExpect(jsonPath("$.tasks[0].constraintCount").value(1))
                .andExpect(jsonPath("$.runs[0].graphVersion").value(3))
                .andExpect(jsonPath("$.mission.userId").doesNotExist())
                .andExpect(jsonPath("$.blueprints").doesNotExist())
                .andExpect(jsonPath("$..checkpoint").doesNotExist())
                .andExpect(jsonPath("$..metadata").doesNotExist())
                .andExpect(jsonPath("$..executionState").doesNotExist())
                .andExpect(jsonPath("$._httpStatus").doesNotExist());
        mvc.perform(get("/api/agentos/v2/missions/mission_1/runs"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.missionId").value("mission_1"))
                .andExpect(jsonPath("$.runs[0].status").value("running"))
                .andExpect(jsonPath("$..checkpoint").doesNotExist());
        assertEquals("/ai/agentos/v2/missions/mission_1/runs", gateway.lastGetPath);
    }

    @Test
    void existingGatewayErrorsKeepStatusFieldsAndOptionalRequestId() throws Exception {
        for (int code : new int[]{403, 404, 409, 422, 502, 503}) {
            Map<String, Object> error = Map.of("code", "AGENTOS_REQUEST_REJECTED", "message", "visible error", "requestId", "request-1");
            for (String suffix : new String[]{"", "/runs"}) {
                gateway.getResponses.put("/ai/agentos/v2/missions/m" + suffix, RecordingAgentOsGateway.response(code, error));
                mvc.perform(get("/api/agentos/v2/missions/m" + suffix)).andExpect(status().is(code))
                        .andExpect(content().json("{\"code\":\"AGENTOS_REQUEST_REJECTED\",\"message\":\"visible error\",\"requestId\":\"request-1\"}", true));
            }
        }
        gateway.getResponses.put("/ai/agentos/v2/missions/m", RecordingAgentOsGateway.response(404,
                Map.of("code", "AGENTOS_REQUEST_REJECTED", "message", "not found")));
        assertInstanceOf(QueryError.class, controller.getMission("m").getBody());
        mvc.perform(get("/api/agentos/v2/missions/m")).andExpect(status().isNotFound())
                .andExpect(content().json("{\"code\":\"AGENTOS_REQUEST_REJECTED\",\"message\":\"not found\"}", true));
    }

    @Test
    void invalidSuccessFailsWithExistingContractErrorEnvelopeWithoutEchoingWireData() throws Exception {
        for (String suffix : new String[]{"", "/runs"}) {
            gateway.getResponses.put("/ai/agentos/v2/missions/m" + suffix,
                    RecordingAgentOsGateway.response(200, Map.of("missionId", MissionQueryFixture.SECRET)));
            String body = mvc.perform(get("/api/agentos/v2/missions/m" + suffix)).andExpect(status().isBadGateway())
                    .andExpect(jsonPath("$.code").value("AGENTOS_CONTRACT_INVALID"))
                    .andExpect(jsonPath("$._httpStatus").doesNotExist()).andReturn().getResponse().getContentAsString();
            assertFalse(body.contains(MissionQueryFixture.SECRET));
        }
    }

    @Test
    void listProjectsTheWhitelistedEnvelopeAndDropsOwnerIdentity() throws Exception {
        gateway.getResponses.put("/ai/agentos/v2/missions?page=1&pageSize=20",
                RecordingAgentOsGateway.response(200, MissionQueryFixture.list()));
        assertInstanceOf(MissionListQuery.class, controller.listMissions(null, 1, 20).getBody());
        mvc.perform(get("/api/agentos/v2/missions"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items[0].missionId").value("mission_1"))
                .andExpect(jsonPath("$.items[0].title").value("审核合同"))
                .andExpect(jsonPath("$.items[0].latestRunId").value("run_1"))
                .andExpect(jsonPath("$.items[0].runCount").value(2))
                .andExpect(jsonPath("$.items[0].userId").doesNotExist())
                .andExpect(jsonPath("$..metadata").doesNotExist())
                .andExpect(jsonPath("$.total").value(1))
                .andExpect(jsonPath("$.source").value("agentos-v2"))
                .andExpect(jsonPath("$._httpStatus").doesNotExist());
        assertEquals("/ai/agentos/v2/missions?page=1&pageSize=20", gateway.lastGetPath);
    }

    @Test
    void listErrorsAndContractViolationsFollowTheExistingErrorRules() throws Exception {
        gateway.getResponses.put("/ai/agentos/v2/missions?page=1&pageSize=20",
                RecordingAgentOsGateway.response(404,
                        Map.of("code", "AGENTOS_REQUEST_REJECTED", "message", "not found")));
        mvc.perform(get("/api/agentos/v2/missions")).andExpect(status().isNotFound())
                .andExpect(content().json("{\"code\":\"AGENTOS_REQUEST_REJECTED\",\"message\":\"not found\"}", true));

        gateway.getResponses.put("/ai/agentos/v2/missions?page=1&pageSize=20",
                RecordingAgentOsGateway.response(200, Map.of("items", List.of(), "total", 0)));
        mvc.perform(get("/api/agentos/v2/missions")).andExpect(status().isBadGateway())
                .andExpect(jsonPath("$.code").value("AGENTOS_CONTRACT_INVALID"))
                .andExpect(jsonPath("$._httpStatus").doesNotExist());
    }

    @Test
    void commandsKeepTheirExistingOwnersAndShapes() throws Exception {
        gateway.postResponses.put("/ai/agentos/v2/missions/m/archive", RecordingAgentOsGateway.response(200,
                Map.of("missionId", "m", "recordState", "archived")));
        assertEquals("archived", controller.archiveMission("m").getBody().get("recordState"));
        assertEquals("/ai/agentos/v2/missions/m/archive", gateway.lastPostPath);
    }
}
