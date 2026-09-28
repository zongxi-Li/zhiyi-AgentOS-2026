package com.kinlin.ai.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.client.AgentOsClient;
import com.kinlin.ai.dto.agentos.AgentOsApiResponse;
import com.kinlin.ai.dto.agentos.AgentOsErrorResponse;
import org.springframework.web.multipart.MultipartFile;

import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Shared recording transport for the split AgentOS controller tests (J1.2B):
 * remembers the exact upstream path / body each controller hands over and
 * returns canned N1.1 envelopes.
 */
final class RecordingAgentOsGateway implements AgentOsClient {

    final ObjectMapper mapper = new ObjectMapper().findAndRegisterModules();
    final Map<String, Map<String, Object>> getResponses = new HashMap<>();
    final Map<String, Map<String, Object>> postResponses = new HashMap<>();
    final Map<String, Map<String, Object>> deleteResponses = new HashMap<>();
    String lastGetPath;
    String lastPostPath;
    Object lastPostBody;
    MultipartFile lastMultipart;
    String lastDeletePath;
    BinaryResponse nextBinary;

    @Override
    public Map<String, Object> get(String path) {
        lastGetPath = path;
        return getResponses.getOrDefault(path, response(404, Map.of("message", "not found")));
    }

    @Override
    public Map<String, Object> post(String path, Object body) {
        lastPostPath = path;
        lastPostBody = body;
        return postResponses.getOrDefault(path, response(404, Map.of("message", "not found")));
    }

    @Override
    public <T extends AgentOsApiResponse> TypedResponse<T> postTyped(
            String path, Object body, Class<T> responseType
    ) {
        lastPostPath = path;
        lastPostBody = body;
        Map<String, Object> configured = postResponses.getOrDefault(
                path, response(404, Map.of("code", "NOT_FOUND", "message", "not found"))
        );
        int status = ((Number) configured.get(INTERNAL_HTTP_STATUS_KEY)).intValue();
        if (status < 200 || status >= 300) {
            return new TypedResponse<>(status, null, new AgentOsErrorResponse(
                    String.valueOf(configured.getOrDefault("code", "AGENTOS_REQUEST_REJECTED")),
                    String.valueOf(configured.getOrDefault("message", configured.getOrDefault(
                            "detail", "AgentOS request was rejected (HTTP " + status + ")."))),
                    configured.get("requestId") instanceof String value ? value : null
            ));
        }
        Map<String, Object> canonical = new LinkedHashMap<>();
        canonical.put("runId", configured.getOrDefault("runId", "run_001"));
        canonical.put("missionId", configured.getOrDefault("missionId", "mission_001"));
        canonical.put("workflowId", configured.getOrDefault("workflowId", "workflow_001"));
        canonical.put("status", configured.getOrDefault("status", "pending"));
        canonical.put("lifecyclePhase", configured.getOrDefault("lifecyclePhase", "planning"));
        canonical.put("runtimeRevision", configured.getOrDefault("runtimeRevision", 0));
        canonical.put("createdAt", configured.getOrDefault("createdAt", "2026-09-27T12:00:00Z"));
        canonical.put("updatedAt", configured.getOrDefault("updatedAt", "2026-09-27T12:00:00Z"));
        if (responseType.getSimpleName().equals("AgentOsReviewResponse")) {
            canonical.put("operationId", configured.getOrDefault("operationId", "op-1"));
            canonical.put("decision", configured.getOrDefault("decision", "approved"));
        }
        if (responseType.getSimpleName().equals("AgentOsOperationResponse")) {
            canonical.put("operation", configured.getOrDefault("operation", "cancel"));
        }
        return new TypedResponse<>(status, mapper.convertValue(canonical, responseType), null);
    }

    @Override
    public Map<String, Object> delete(String path) {
        lastDeletePath = path;
        return deleteResponses.getOrDefault(path, response(404, Map.of("message", "not found")));
    }

    @Override
    public BinaryResponse getBinary(String path) {
        lastGetPath = path;
        if (nextBinary != null) {
            BinaryResponse given = nextBinary;
            nextBinary = null;
            return given;
        }
        return new BinaryResponse(404, "not found".getBytes(), "text/plain", null);
    }

    @Override
    public Map<String, Object> postMultipart(String path, MultipartFile file) {
        lastPostPath = path;
        lastMultipart = file;
        return postResponses.getOrDefault(path, response(404, Map.of("message", "not found")));
    }

    static Map<String, Object> response(int status, Map<String, Object> body) {
        Map<String, Object> result = new LinkedHashMap<>(body);
        result.put(AgentOsClient.INTERNAL_HTTP_STATUS_KEY, status);
        return result;
    }
}
