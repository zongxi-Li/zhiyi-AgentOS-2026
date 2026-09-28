package com.kinlin.ai.controller;

import com.kinlin.ai.client.AgentOsClient;
import com.kinlin.ai.dto.agentos.AgentOsApiResponse;
import org.springframework.http.ResponseEntity;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Shared non-business API projection for the split AgentOS controllers (J1.2B):
 * strips the internal status marker and projects the upstream status onto the
 * HTTP response. Error-envelope semantics stay in the gateway transport; this
 * class owns no paths, no transport and no business fallback.
 */
final class AgentOsControllerSupport {

    private AgentOsControllerSupport() {
    }

    static ResponseEntity<Map<String, Object>> response(Map<String, Object> payload) {
        Map<String, Object> body = new LinkedHashMap<>(payload == null ? Map.of() : payload);
        Object status = body.remove(AgentOsClient.INTERNAL_HTTP_STATUS_KEY);
        int code = status instanceof Number number ? number.intValue() : 200;
        return ResponseEntity.status(code).body(body);
    }

    static <T extends AgentOsApiResponse> ResponseEntity<? extends AgentOsApiResponse> typedResponse(
            AgentOsClient.TypedResponse<T> response
    ) {
        AgentOsApiResponse body = response.error() == null ? response.body() : response.error();
        return ResponseEntity.status(response.status()).body(body);
    }
}
