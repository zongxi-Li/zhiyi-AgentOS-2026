package com.kinlin.ai.controller;

import com.kinlin.ai.client.AgentOsClient;
import com.kinlin.ai.dto.agentos.AgentOsApiResponse;
import com.kinlin.ai.dto.agentos.AgentOsMissionCreateRequest;
import com.kinlin.ai.dto.agentos.AgentOsMissionResponse;
import com.kinlin.ai.gateway.AgentOsPaths;
import com.kinlin.ai.projection.common.dto.QueryResponse;
import com.kinlin.ai.projection.mission.mapper.MissionProjectionMapper;
import com.kinlin.ai.projection.mission.mapper.MissionSemanticProjectionMapper;
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

    @PostMapping("/missions/{missionId}/semantics")
    public ResponseEntity<Map<String, Object>> editSemantics(
            @PathVariable String missionId, @RequestBody Map<String, Object> body) {
        return AgentOsControllerSupport.response(gateway.post(AgentOsPaths.mission(missionId) + "/semantics", body));
    }

    @GetMapping("/missions/{missionId}/semantics")
    public ResponseEntity<QueryResponse> getSemantics(@PathVariable String missionId) {
        return AgentOsControllerSupport.projectedResponse(gateway.get(AgentOsPaths.mission(missionId) + "/semantics"),
                MissionSemanticProjectionMapper::view);
    }

    @GetMapping("/missions/{missionId}/semantics/commits")
    public ResponseEntity<QueryResponse> getSemanticCommits(@PathVariable String missionId) {
        return AgentOsControllerSupport.projectedResponse(gateway.get(AgentOsPaths.mission(missionId) + "/semantics/commits"),
                MissionSemanticProjectionMapper::commits);
    }

    @GetMapping("/missions/{missionId}/semantics/receipts/{operationId}")
    public ResponseEntity<QueryResponse> getSemanticReceipt(@PathVariable String missionId, @PathVariable String operationId) {
        return AgentOsControllerSupport.projectedResponse(gateway.get(AgentOsPaths.mission(missionId) + "/semantics/receipts/" + AgentOsPaths.segment(operationId)),
                MissionSemanticProjectionMapper::receipt);
    }

    @GetMapping("/missions/{missionId}/runs/{runId}/revision")
    public ResponseEntity<QueryResponse> getRunRevision(@PathVariable String missionId, @PathVariable String runId) {
        return AgentOsControllerSupport.projectedResponse(gateway.get(AgentOsPaths.mission(missionId) + "/runs/" + AgentOsPaths.segment(runId) + "/revision"),
                MissionSemanticProjectionMapper::revision);
    }

    @PostMapping("/missions/{missionId}/runs/{runId}/revision")
    public ResponseEntity<Map<String, Object>> decideRunRevision(@PathVariable String missionId, @PathVariable String runId, @RequestBody Map<String, Object> request) {
        return AgentOsControllerSupport.response(gateway.post(AgentOsPaths.mission(missionId) + "/runs/" + AgentOsPaths.segment(runId) + "/revision", request));
    }

    @PostMapping("/missions/{missionId}/runs/{runId}/revision/{operationId}/apply")
    public ResponseEntity<Map<String, Object>> applyRunRevision(@PathVariable String missionId, @PathVariable String runId, @PathVariable String operationId) {
        return AgentOsControllerSupport.response(gateway.post(AgentOsPaths.mission(missionId) + "/runs/" + AgentOsPaths.segment(runId) + "/revision/" + AgentOsPaths.segment(operationId) + "/apply", Map.of()));
    }

    @GetMapping("/missions")
    public ResponseEntity<QueryResponse> listMissions(
            @RequestParam(required = false) String status,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "20") int pageSize
    ) {
        Map<String, String> params = new LinkedHashMap<>();
        params.put("status", status);
        params.put("page", String.valueOf(page));
        params.put("pageSize", String.valueOf(pageSize));
        return AgentOsControllerSupport.projectedResponse(
                gateway.get(AgentOsPaths.query(AgentOsPaths.missions(), params)),
                MissionProjectionMapper::list);
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
