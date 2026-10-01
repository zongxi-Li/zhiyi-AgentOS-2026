package com.kinlin.ai.controller;

import com.kinlin.ai.client.AgentOsClient;
import com.kinlin.ai.dto.agentos.AgentOsApiResponse;
import com.kinlin.ai.dto.agentos.AgentOsMissionCreateRequest;
import com.kinlin.ai.dto.agentos.AgentOsMissionResponse;
import com.kinlin.ai.gateway.AgentOsPaths;
import com.kinlin.ai.projection.common.dto.QueryResponse;
import com.kinlin.ai.projection.mission.mapper.MissionProjectionMapper;
import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * MISSION ownership: mission create / read / list / archive / restore / delete
 * plus the mission-scoped run listing (a mission view). Run creation lives in
 * {@link AgentOsRunController} because its lifecycle is a run's.
 */
@RestController
@RequestMapping("/api/agentos/v2")
public class AgentOsMissionController {

    private final AgentOsClient gateway;

    public AgentOsMissionController(AgentOsClient gateway) {
        this.gateway = gateway;
    }

    @PostMapping("/missions")
    public ResponseEntity<? extends AgentOsApiResponse> createMission(
            @Valid @RequestBody AgentOsMissionCreateRequest body
    ) {
        return AgentOsControllerSupport.typedResponse(gateway.postTyped(
                AgentOsPaths.missions(), body, AgentOsMissionResponse.class
        ));
    }

    @GetMapping("/missions")
    public ResponseEntity<Map<String, Object>> listMissions(
            @RequestParam(required = false) String status,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "20") int pageSize
    ) {
        Map<String, String> params = new LinkedHashMap<>();
        params.put("status", status);
        params.put("page", String.valueOf(page));
        params.put("pageSize", String.valueOf(pageSize));
        return AgentOsControllerSupport.response(
                gateway.get(AgentOsPaths.query(AgentOsPaths.missions(), params)));
    }

    @GetMapping("/missions/{missionId}")
    public ResponseEntity<QueryResponse> getMission(@PathVariable String missionId) {
        return AgentOsControllerSupport.projectedResponse(gateway.get(AgentOsPaths.mission(missionId)),
                MissionProjectionMapper::detail);
    }

    @GetMapping("/missions/{missionId}/runs")
    public ResponseEntity<QueryResponse> getMissionRuns(@PathVariable String missionId) {
        return AgentOsControllerSupport.projectedResponse(gateway.get(AgentOsPaths.missionRuns(missionId)),
                MissionProjectionMapper::history);
    }

    @PostMapping("/missions/{missionId}/archive")
    public ResponseEntity<Map<String, Object>> archiveMission(@PathVariable String missionId) {
        return AgentOsControllerSupport.response(
                gateway.post(AgentOsPaths.mission(missionId) + "/archive", Map.of()));
    }

    @PostMapping("/missions/{missionId}/restore")
    public ResponseEntity<Map<String, Object>> restoreMission(@PathVariable String missionId) {
        return AgentOsControllerSupport.response(
                gateway.post(AgentOsPaths.mission(missionId) + "/restore", Map.of()));
    }

    @DeleteMapping("/missions/{missionId}")
    public ResponseEntity<Map<String, Object>> deleteMission(@PathVariable String missionId) {
        return AgentOsControllerSupport.response(gateway.delete(AgentOsPaths.mission(missionId)));
    }
}
