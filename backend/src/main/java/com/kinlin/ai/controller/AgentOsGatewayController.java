package com.kinlin.ai.controller;

import com.kinlin.ai.dto.agentos.AgentOsReviewRequest;
import com.kinlin.ai.dto.agentos.AgentOsMissionCreateRequest;
import com.kinlin.ai.service.AgentOsGatewayService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
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

/** Authorized HTTP projection of the Python-owned AgentOS v2 runtime. */
@RestController
@RequestMapping("/api/agentos/v2")
@RequiredArgsConstructor
public class AgentOsGatewayController {

    private static final String UPSTREAM_ROOT = "/ai/agentos/v2";
    private final AgentOsGatewayService gateway;

    @PostMapping("/missions")
    public ResponseEntity<Map<String, Object>> createMission(@Valid @RequestBody AgentOsMissionCreateRequest body) {
        return response(gateway.post(UPSTREAM_ROOT + "/missions", body));
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
        params.put("summary", summary == null ? null : summary.toString());
        params.put("page", String.valueOf(page));
        params.put("pageSize", String.valueOf(pageSize));
        return response(gateway.get(query(UPSTREAM_ROOT + "/runs", params)));
    }

    @GetMapping("/runs/{runId}")
    public ResponseEntity<Map<String, Object>> getRun(@PathVariable String runId) {
        return response(gateway.get(runPath(runId)));
    }

    @GetMapping("/runs/{runId}/history-config")
    public ResponseEntity<Map<String, Object>> getHistoryConfig(@PathVariable String runId) {
        return response(gateway.get(runPath(runId) + "/history-config"));
    }

    @GetMapping("/runs/{runId}/graph")
    public ResponseEntity<Map<String, Object>> getGraph(@PathVariable String runId) {
        return response(gateway.get(runPath(runId) + "/graph"));
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

    private String runPath(String runId) {
        return UPSTREAM_ROOT + "/runs/" + segment(runId);
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
