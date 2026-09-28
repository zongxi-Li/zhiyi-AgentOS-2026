package com.kinlin.ai.client;

import com.kinlin.ai.dto.agentos.AgentOsApiResponse;
import com.kinlin.ai.dto.agentos.AgentOsErrorResponse;
import org.springframework.web.multipart.MultipartFile;

import java.util.Map;

/**
 * What the Java platform needs from the Python-owned AgentOS v2 runtime
 * (the upstream root defined once in {@code AgentOsPaths}).
 *
 * <p>This is the northbound client contract of the AgentOS transport family: callers
 * (currently the authorized gateway controller) depend on this interface, never on the
 * WebClient-holding implementation. Error mapping follows the frozen N1.1 envelope —
 * failures are returned as AGENTOS_* payloads / {@link TypedResponse#error()}, not
 * thrown, and never leak upstream sensitive fields. SSE streaming is deliberately
 * out of scope (sole opener stays {@code AiSseGatewayService}, frozen until N2).</p>
 */
public interface AgentOsClient {

    /** Marker key holding the upstream HTTP status inside map-based results. */
    String INTERNAL_HTTP_STATUS_KEY = "_httpStatus";

    Map<String, Object> get(String path);

    Map<String, Object> post(String path, Object body);

    <T extends AgentOsApiResponse> TypedResponse<T> postTyped(String path, Object body, Class<T> responseType);

    Map<String, Object> delete(String path);

    BinaryResponse getBinary(String path);

    Map<String, Object> postMultipart(String path, MultipartFile file);

    record BinaryResponse(int status, byte[] body, String contentType, String contentDisposition) { }

    record TypedResponse<T extends AgentOsApiResponse>(
            int status,
            T body,
            AgentOsErrorResponse error
    ) { }
}
