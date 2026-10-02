package com.kinlin.ai.controller;

import com.kinlin.ai.client.AgentOsClient;
import com.kinlin.ai.gateway.AgentOsPaths;
import com.kinlin.ai.projection.common.dto.QueryResponse;
import com.kinlin.ai.projection.resource.mapper.ResourceUsageProjectionMapper;
import com.kinlin.ai.projection.run.mapper.RunProjectionMapper;
import com.kinlin.ai.projection.graph.mapper.GraphProjectionMapper;
import com.kinlin.ai.projection.memory.mapper.MemoryEventsProjectionMapper;
import com.kinlin.ai.projection.provenance.mapper.ProvenanceProjectionMapper;
import com.kinlin.ai.projection.trace.mapper.TraceProjectionMapper;
import com.kinlin.ai.projection.workspace.mapper.WorkspaceProjectionMapper;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * OBSERVATION ownership: read-only projections over a mission or run —
 * workspace, history-config, graph, execution tree, resource usage, trace,
 * memory events, provenance, checkpoints, and the upstream identity health probe.
 * No command lives here.
 */
@RestController
@RequestMapping("/api/agentos/v2")
public class AgentOsObservationController {

    private final AgentOsClient gateway;

    public AgentOsObservationController(AgentOsClient gateway) {
        this.gateway = gateway;
    }

    @GetMapping("/missions/{missionId}/workspace")
    public ResponseEntity<QueryResponse> getMissionWorkspace(
            @PathVariable String missionId,
            @RequestParam(required = false) String runId
    ) {
        Map<String, String> params = new LinkedHashMap<>();
        params.put("runId", runId);
        return AgentOsControllerSupport.projectedResponse(gateway.get(AgentOsPaths.query(
                AgentOsPaths.mission(missionId) + "/workspace", params)), WorkspaceProjectionMapper::workspace);
    }

    @GetMapping("/identity/health")
    public ResponseEntity<Map<String, Object>> getIdentityHealth() {
        return AgentOsControllerSupport.response(gateway.get(AgentOsPaths.identityHealth()));
    }

    @GetMapping("/runs/{runId}/history-config")
    public ResponseEntity<Map<String, Object>> getHistoryConfig(@PathVariable String runId) {
        return AgentOsControllerSupport.response(
                gateway.get(AgentOsPaths.run(runId) + "/history-config"));
    }

    @GetMapping("/runs/{runId}/graph")
    public ResponseEntity<QueryResponse> getGraph(@PathVariable String runId) {
        return AgentOsControllerSupport.projectedResponse(gateway.get(AgentOsPaths.run(runId) + "/graph"), GraphProjectionMapper::graph);
    }

    @GetMapping("/runs/{runId}/execution-tree")
    public ResponseEntity<QueryResponse> getExecutionTree(@PathVariable String runId) {
        return AgentOsControllerSupport.projectedResponse(
                gateway.get(AgentOsPaths.run(runId) + "/execution-tree"), RunProjectionMapper::tree);
    }

    @GetMapping("/runs/{runId}/resource-usage")
    public ResponseEntity<QueryResponse> getResourceUsage(@PathVariable String runId) {
        return AgentOsControllerSupport.projectedResponse(
                gateway.get(AgentOsPaths.run(runId) + "/resource-usage"), ResourceUsageProjectionMapper::usage);
    }

    @GetMapping("/runs/{runId}/resource-usage/calls")
    public ResponseEntity<QueryResponse> getResourceUsageCalls(
            @PathVariable String runId,
            @RequestParam(required = false) String stepId,
            @RequestParam(required = false) String cursor,
            @RequestParam(defaultValue = "20") int pageSize
    ) {
        Map<String, String> params = new LinkedHashMap<>();
        params.put("stepId", stepId);
        params.put("cursor", cursor);
        params.put("pageSize", String.valueOf(pageSize));
        return AgentOsControllerSupport.projectedResponse(gateway.get(AgentOsPaths.query(
                AgentOsPaths.run(runId) + "/resource-usage/calls", params)),
                ResourceUsageProjectionMapper::callPage);
    }

    @GetMapping("/runs/{runId}/trace")
    public ResponseEntity<QueryResponse> getTrace(
            @PathVariable String runId,
            @RequestParam(required = false) String view
    ) {
        Map<String, String> params = new LinkedHashMap<>();
        params.put("view", view);
        return AgentOsControllerSupport.projectedResponse(gateway.get(AgentOsPaths.query(
                AgentOsPaths.run(runId) + "/trace", params)), TraceProjectionMapper::trace);
    }

    @GetMapping("/runs/{runId}/memory-events")
    public ResponseEntity<QueryResponse> getMemoryEvents(@PathVariable String runId) {
        return AgentOsControllerSupport.projectedResponse(
                gateway.get(AgentOsPaths.run(runId) + "/memory-events"), MemoryEventsProjectionMapper::memoryEvents);
    }

    @GetMapping("/runs/{runId}/provenance")
    public ResponseEntity<QueryResponse> getProvenance(@PathVariable String runId) {
        return AgentOsControllerSupport.projectedResponse(
                gateway.get(AgentOsPaths.run(runId) + "/provenance"), ProvenanceProjectionMapper::provenance);
    }

    @GetMapping("/runs/{runId}/checkpoints")
    public ResponseEntity<Map<String, Object>> getCheckpoints(@PathVariable String runId) {
        return AgentOsControllerSupport.response(
                gateway.get(AgentOsPaths.run(runId) + "/checkpoints"));
    }
}
