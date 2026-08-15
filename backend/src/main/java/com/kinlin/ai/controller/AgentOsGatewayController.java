package com.kinlin.ai.controller;

import com.kinlin.ai.dto.agentos.AgentOsReviewRequest;
import com.kinlin.ai.dto.agentos.AgentOsRunCreateRequest;
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

    @PostMapping("/runs")
    public ResponseEntity<Map<String, Object>> createRun(@Valid @RequestBody AgentOsRunCreateRequest body) {
        return response(gateway.post(UPSTREAM_ROOT + "/runs", body));
    }

    @GetMapping("/runs")
    public ResponseEntity<Map<String, Object>> listRuns(
            @RequestParam(required = false) String status,
            @RequestParam(required = false) String domain,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "20") int pageSize
    ) {
        Map<String, String> params = new LinkedHashMap<>();
        params.put("status", status);
        params.put("domain", domain);
        params.put("page", String.valueOf(page));
        params.put("pageSize", String.valueOf(pageSize));
        return response(gateway.get(query(UPSTREAM_ROOT + "/runs", params)));
    }

    @GetMapping("/runs/{runId}")
    public ResponseEntity<Map<String, Object>> getRun(@PathVariable String runId) {
        return response(gateway.get(runPath(runId)));
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
