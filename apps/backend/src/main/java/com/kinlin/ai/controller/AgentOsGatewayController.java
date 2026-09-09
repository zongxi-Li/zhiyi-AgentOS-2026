package com.kinlin.ai.controller;

import com.kinlin.ai.dto.agentos.AgentOsReviewRequest;
import com.kinlin.ai.dto.agentos.AgentOsMaterialCreateRequest;
import com.kinlin.ai.dto.agentos.AgentOsMissionCreateRequest;
import com.kinlin.ai.dto.agentos.AgentOsMissionRunCreateRequest;
import com.kinlin.ai.gateway.AiSseGatewayService;
import com.kinlin.ai.service.AgentOsGatewayService;
import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.util.UriUtils;

import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.http.codec.ServerSentEvent;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

/** Authorized HTTP projection of the Python-owned AgentOS v2 runtime. */
@RestController
@RequestMapping("/api/agentos/v2")
public class AgentOsGatewayController {

    private static final String UPSTREAM_ROOT = "/ai/agentos/v2";
    private final AgentOsGatewayService gateway;
    private final AiSseGatewayService sseGateway;

    public AgentOsGatewayController(AgentOsGatewayService gateway) {
        this(gateway, null);
    }

    @org.springframework.beans.factory.annotation.Autowired
    public AgentOsGatewayController(AgentOsGatewayService gateway, AiSseGatewayService sseGateway) {
        this.gateway = gateway;
        this.sseGateway = sseGateway;
    }

    @PostMapping("/missions")
    public ResponseEntity<Map<String, Object>> createMission(@Valid @RequestBody AgentOsMissionCreateRequest body) {
        return response(gateway.post(UPSTREAM_ROOT + "/missions", body));
    }

    @PostMapping("/materials")
    public ResponseEntity<Map<String, Object>> createMaterial(
            @Valid @RequestBody AgentOsMaterialCreateRequest body
    ) {
        return response(gateway.post(UPSTREAM_ROOT + "/materials", body));
    }

    @GetMapping("/materials/{manifestId}")
    public ResponseEntity<Map<String, Object>> getMaterial(@PathVariable String manifestId) {
        return response(gateway.get(UPSTREAM_ROOT + "/materials/" + segment(manifestId)));
    }

    @GetMapping("/resources")
    public ResponseEntity<Map<String, Object>> getResources() {
        return response(gateway.get(UPSTREAM_ROOT + "/resources"));
    }

    @PostMapping("/resources/register")
    public ResponseEntity<Map<String, Object>> registerResource(@RequestBody Map<String, Object> body) {
        return response(gateway.post(UPSTREAM_ROOT + "/resources/register", body));
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
        return response(gateway.get(query(UPSTREAM_ROOT + "/missions", params)));
    }

    @GetMapping("/missions/{missionId}")
    public ResponseEntity<Map<String, Object>> getMission(@PathVariable String missionId) {
        return response(gateway.get(missionPath(missionId)));
    }

    @GetMapping("/missions/{missionId}/runs")
    public ResponseEntity<Map<String, Object>> getMissionRuns(@PathVariable String missionId) {
        return response(gateway.get(missionPath(missionId) + "/runs"));
    }

    @PostMapping("/missions/{missionId}/runs")
    public ResponseEntity<Map<String, Object>> createMissionRun(
            @PathVariable String missionId,
            @Valid @RequestBody AgentOsMissionRunCreateRequest body
    ) {
        return response(gateway.post(missionPath(missionId) + "/runs", body));
    }

    @GetMapping("/missions/{missionId}/workspace")
    public ResponseEntity<Map<String, Object>> getMissionWorkspace(
            @PathVariable String missionId,
            @RequestParam(required = false) String runId
    ) {
        Map<String, String> params = new LinkedHashMap<>();
        params.put("runId", runId);
        return response(gateway.get(query(missionPath(missionId) + "/workspace", params)));
    }

    @PostMapping("/missions/{missionId}/archive")
    public ResponseEntity<Map<String, Object>> archiveMission(@PathVariable String missionId) {
        return response(gateway.post(missionPath(missionId) + "/archive", Map.of()));
    }

    @PostMapping("/missions/{missionId}/restore")
    public ResponseEntity<Map<String, Object>> restoreMission(@PathVariable String missionId) {
        return response(gateway.post(missionPath(missionId) + "/restore", Map.of()));
    }

    @DeleteMapping("/missions/{missionId}")
    public ResponseEntity<Map<String, Object>> deleteMission(@PathVariable String missionId) {
        return response(gateway.delete(missionPath(missionId)));
    }

    @GetMapping("/runs")
    public ResponseEntity<Map<String, Object>> listRuns(
            @RequestParam(required = false) String status,
            @RequestParam(required = false) String statuses,
            @RequestParam(required = false) String domain,
            @RequestParam(required = false) String workflowId,
            @RequestParam(required = false) String missionId,
            @RequestParam(required = false) String lifecyclePhase,
            @RequestParam(required = false) String source,
            @RequestParam(required = false) String sources,
            @RequestParam(required = false) String recordState,
            @RequestParam(required = false) Boolean summary,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "20") int pageSize
    ) {
        Map<String, String> params = new LinkedHashMap<>();
        params.put("status", status);
        params.put("statuses", statuses);
        params.put("domain", domain);
        params.put("workflowId", workflowId);
        params.put("missionId", missionId);
        params.put("lifecyclePhase", lifecyclePhase);
        params.put("source", source);
        params.put("sources", sources);
        params.put("recordState", recordState);
        params.put("summary", summary == null ? null : summary.toString());
        params.put("page", String.valueOf(page));
        params.put("pageSize", String.valueOf(pageSize));
        return response(gateway.get(query(UPSTREAM_ROOT + "/runs", params)));
    }

    @GetMapping("/runs/{runId}")
    public ResponseEntity<Map<String, Object>> getRun(@PathVariable String runId) {
        return response(gateway.get(runPath(runId)));
    }

    @GetMapping(value = "/runs/{runId}/events", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public Mono<ResponseEntity<Flux<ServerSentEvent<String>>>> streamRunEvents(@PathVariable String runId) {
        if (sseGateway == null) {
            return Mono.error(new IllegalStateException("RuntimeEvent SSE gateway is not configured"));
        }
        return sseGateway.openGet(runPath(runId) + "/events");
    }

    @GetMapping("/runs/{runId}/history-config")
    public ResponseEntity<Map<String, Object>> getHistoryConfig(@PathVariable String runId) {
        return response(gateway.get(runPath(runId) + "/history-config"));
    }

    @GetMapping("/runs/{runId}/graph")
    public ResponseEntity<Map<String, Object>> getGraph(@PathVariable String runId) {
        return response(gateway.get(runPath(runId) + "/graph"));
    }

    @GetMapping("/runs/{runId}/execution-tree")
    public ResponseEntity<Map<String, Object>> getExecutionTree(@PathVariable String runId) {
        return response(gateway.get(runPath(runId) + "/execution-tree"));
    }

    @GetMapping("/runs/{runId}/resource-usage")
    public ResponseEntity<Map<String, Object>> getResourceUsage(@PathVariable String runId) {
        return response(gateway.get(runPath(runId) + "/resource-usage"));
    }

    @GetMapping("/runs/{runId}/resource-usage/calls")
    public ResponseEntity<Map<String, Object>> getResourceUsageCalls(
            @PathVariable String runId,
            @RequestParam(required = false) String stepId,
            @RequestParam(required = false) String cursor,
            @RequestParam(defaultValue = "20") int pageSize
    ) {
        Map<String, String> params = new LinkedHashMap<>();
        params.put("stepId", stepId);
        params.put("cursor", cursor);
        params.put("pageSize", String.valueOf(pageSize));
        return response(gateway.get(query(runPath(runId) + "/resource-usage/calls", params)));
    }

    @GetMapping("/runs/{runId}/artifacts")
    public ResponseEntity<Map<String, Object>> getArtifacts(@PathVariable String runId) {
        return response(gateway.get(runPath(runId) + "/artifacts"));
    }

    @GetMapping("/runs/{runId}/artifacts/{manifestId}")
    public ResponseEntity<Map<String, Object>> getArtifact(
            @PathVariable String runId,
            @PathVariable String manifestId
    ) {
        return response(gateway.get(artifactPath(runId, manifestId)));
    }

    @GetMapping("/runs/{runId}/artifacts/{manifestId}/fragments")
    public ResponseEntity<Map<String, Object>> getArtifactFragments(
            @PathVariable String runId,
            @PathVariable String manifestId,
            @RequestParam(required = false) String cursor,
            @RequestParam(defaultValue = "20") int pageSize
    ) {
        Map<String, String> params = new LinkedHashMap<>();
        params.put("cursor", cursor);
        params.put("pageSize", String.valueOf(pageSize));
        return response(gateway.get(query(artifactPath(runId, manifestId) + "/fragments", params)));
    }

    @GetMapping("/runs/{runId}/artifacts/{manifestId}/download")
    public ResponseEntity<byte[]> downloadArtifact(
            @PathVariable String runId,
            @PathVariable String manifestId
    ) {
        AgentOsGatewayService.BinaryResponse upstream = gateway.getBinary(
                artifactPath(runId, manifestId) + "/download"
        );
        HttpHeaders headers = new HttpHeaders();
        try {
            headers.setContentType(MediaType.parseMediaType(upstream.contentType()));
        } catch (IllegalArgumentException ignored) {
            headers.setContentType(MediaType.APPLICATION_OCTET_STREAM);
        }
        if (upstream.contentDisposition() != null && !upstream.contentDisposition().isBlank()) {
            headers.set(HttpHeaders.CONTENT_DISPOSITION, upstream.contentDisposition());
        }
        return ResponseEntity.status(upstream.status()).headers(headers).body(upstream.body());
    }

    @GetMapping("/identity/health")
    public ResponseEntity<Map<String, Object>> getIdentityHealth() {
        return response(gateway.get(UPSTREAM_ROOT + "/identity/health"));
    }

    @GetMapping("/runs/{runId}/outputs/{outputRef}")
    public ResponseEntity<Map<String, Object>> getOutput(
            @PathVariable String runId,
            @PathVariable String outputRef
    ) {
        return response(gateway.get(runPath(runId) + "/outputs/" + segment(outputRef)));
    }

    @GetMapping("/runs/{runId}/legacy-outputs")
    public ResponseEntity<Map<String, Object>> getLegacyOutputs(@PathVariable String runId) {
        return response(gateway.get(runPath(runId) + "/legacy-outputs"));
    }

    @GetMapping("/runs/{runId}/trace")
    public ResponseEntity<Map<String, Object>> getTrace(@PathVariable String runId) {
        return response(gateway.get(runPath(runId) + "/trace"));
    }

    @GetMapping("/runs/{runId}/memory-events")
    public ResponseEntity<Map<String, Object>> getMemoryEvents(@PathVariable String runId) {
        return response(gateway.get(runPath(runId) + "/memory-events"));
    }

    @GetMapping("/runs/{runId}/provenance")
    public ResponseEntity<Map<String, Object>> getProvenance(@PathVariable String runId) {
        return response(gateway.get(runPath(runId) + "/provenance"));
    }

    @GetMapping("/runs/{runId}/checkpoints")
    public ResponseEntity<Map<String, Object>> getCheckpoints(@PathVariable String runId) {
        return response(gateway.get(runPath(runId) + "/checkpoints"));
    }

    @GetMapping("/runs/{runId}/reviews")
    public ResponseEntity<Map<String, Object>> getReviews(@PathVariable String runId) {
        return response(gateway.get(runPath(runId) + "/reviews"));
    }

    @PostMapping("/runs/{runId}/reviews")
    public ResponseEntity<Map<String, Object>> applyReview(
            @PathVariable String runId,
            @Valid @RequestBody AgentOsReviewRequest body
    ) {
        return response(gateway.post(runPath(runId) + "/reviews", body));
    }

    @PostMapping("/runs/{runId}/cancel")
    public ResponseEntity<Map<String, Object>> cancelRun(@PathVariable String runId) {
        return response(gateway.post(runPath(runId) + "/cancel", Map.of()));
    }

    private String runPath(String runId) {
        return UPSTREAM_ROOT + "/runs/" + segment(runId);
    }

    private String artifactPath(String runId, String manifestId) {
        return runPath(runId) + "/artifacts/" + segment(manifestId);
    }

    private String missionPath(String missionId) {
        return UPSTREAM_ROOT + "/missions/" + segment(missionId);
    }

    private String segment(String value) {
        return UriUtils.encodePathSegment(value, StandardCharsets.UTF_8);
    }

    private String query(String basePath, Map<String, String> params) {
        StringBuilder result = new StringBuilder(basePath);
        boolean first = true;
        for (Map.Entry<String, String> entry : params.entrySet()) {
            if (entry.getValue() == null || entry.getValue().isBlank()) {
                continue;
            }
            result.append(first ? '?' : '&');
            first = false;
            result.append(entry.getKey()).append('=')
                    .append(UriUtils.encodeQueryParam(entry.getValue(), StandardCharsets.UTF_8));
        }
        return result.toString();
    }

    private ResponseEntity<Map<String, Object>> response(Map<String, Object> payload) {
        Map<String, Object> body = new LinkedHashMap<>(payload == null ? Map.of() : payload);
        Object status = body.remove(AgentOsGatewayService.INTERNAL_HTTP_STATUS_KEY);
        int code = status instanceof Number number ? number.intValue() : 200;
        return ResponseEntity.status(code).body(body);
    }
}
