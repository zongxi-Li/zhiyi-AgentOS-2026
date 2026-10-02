package com.kinlin.ai.controller;

import com.kinlin.ai.client.AgentOsClient;
import com.kinlin.ai.dto.agentos.AgentOsApiResponse;
import com.kinlin.ai.projection.common.dto.QueryError;
import com.kinlin.ai.projection.common.dto.QueryResponse;
import org.springframework.http.ResponseEntity;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.function.Function;

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

    static <T extends QueryResponse> ResponseEntity<QueryResponse> projectedResponse(
            Map<String, Object> payload, Function<Map<String, Object>, T> mapper
    ) {
        ResponseEntity<Map<String, Object>> upstream = response(payload);
        Map<String, Object> body = upstream.getBody();
        if (!upstream.getStatusCode().is2xxSuccessful()) {
            // The existing gateway already owns status selection, sanitization and error normalization.
            return ResponseEntity.status(upstream.getStatusCode()).body(new QueryError(
                    (String) body.get("code"), (String) body.get("message"), (String) body.get("requestId")));
        }
        try {
            return ResponseEntity.status(upstream.getStatusCode()).body(mapper.apply(body));
        } catch (IllegalArgumentException | ArithmeticException invalid) {
            return ResponseEntity.status(502).body(new QueryError("AGENTOS_CONTRACT_INVALID",
                    "AgentOS service returned an invalid response contract.", null));
        }
    }
}
