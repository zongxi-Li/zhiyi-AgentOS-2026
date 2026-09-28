package com.kinlin.ai.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.config.AgentProperties;
import com.kinlin.ai.dto.agentos.AgentOsApiResponse;
import com.kinlin.ai.dto.agentos.AgentOsErrorResponse;
import com.kinlin.ai.gateway.AgentOsPaths;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.http.client.MultipartBodyBuilder;
import org.springframework.web.reactive.function.BodyInserters;
import org.springframework.web.multipart.MultipartFile;
import reactor.core.publisher.Mono;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.HashMap;
import java.util.Map;

/** Stateless transport and error-mapping boundary for AgentOS v2. */
@Slf4j
@Service
public class AgentOsGatewayService {

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper().findAndRegisterModules();
    public static final String INTERNAL_HTTP_STATUS_KEY = "_httpStatus";

    public record BinaryResponse(int status, byte[] body, String contentType, String contentDisposition) { }
    public record TypedResponse<T extends AgentOsApiResponse>(
            int status,
            T body,
            AgentOsErrorResponse error
    ) { }

    private final WebClient webClient;
    private final AgentProperties properties;

    public AgentOsGatewayService(WebClient transport, AgentProperties properties) {
        this.webClient = transport;
        this.properties = properties;
    }

    public Map<String, Object> get(String path) {
        if (!properties.isEnabled()) {
            return error(HttpStatus.SERVICE_UNAVAILABLE.value(), "AGENTOS_GATEWAY_DISABLED",
                    "AgentOS gateway is disabled.");
        }
        try {
            return webClient.get().uri(path)
                    .exchangeToMono(response -> mapResponse(response.statusCode().value(), response.bodyToMono(String.class)))
                    .timeout(Duration.ofMillis(getTimeoutMs(path)))
                    .onErrorResume(failure -> Mono.just(unavailable(path, failure)))
                    .block();
        } catch (Exception failure) {
            return unavailable(path, failure);
        }
    }

    public Map<String, Object> post(String path, Object body) {
        if (!properties.isEnabled()) {
            return error(HttpStatus.SERVICE_UNAVAILABLE.value(), "AGENTOS_GATEWAY_DISABLED",
                    "AgentOS gateway is disabled.");
        }
        try {
            return webClient.post().uri(path).bodyValue(body == null ? Map.of() : body)
                    .exchangeToMono(response -> mapResponse(response.statusCode().value(), response.bodyToMono(String.class)))
                    .timeout(Duration.ofMillis(postTimeoutMs(path)))
                    .onErrorResume(failure -> Mono.just(unavailable(path, failure)))
                    .block();
        } catch (Exception failure) {
            return unavailable(path, failure);
        }
    }

    public <T extends AgentOsApiResponse> TypedResponse<T> postTyped(
            String path,
            Object body,
            Class<T> responseType
    ) {
        if (!properties.isEnabled()) {
            return typedError(HttpStatus.SERVICE_UNAVAILABLE.value(), "AGENTOS_GATEWAY_DISABLED",
                    "AgentOS gateway is disabled.", null);
        }
        try {
            return webClient.post().uri(path).bodyValue(body == null ? Map.of() : body)
                    .exchangeToMono(response -> typedResponse(
                            response.statusCode().value(),
                            response.bodyToMono(String.class),
                            responseType
                    ))
                    .timeout(Duration.ofMillis(postTimeoutMs(path)))
                    .onErrorResume(failure -> Mono.just(typedUnavailable(path, failure)))
                    .block();
        } catch (Exception failure) {
            return typedUnavailable(path, failure);
        }
    }

    public Map<String, Object> delete(String path) {
        if (!properties.isEnabled()) {
            return error(HttpStatus.SERVICE_UNAVAILABLE.value(), "AGENTOS_GATEWAY_DISABLED",
                    "AgentOS gateway is disabled.");
        }
        try {
            return webClient.delete().uri(path)
                    .exchangeToMono(response -> mapResponse(response.statusCode().value(), response.bodyToMono(String.class)))
                    .timeout(Duration.ofMillis(properties.getTimeoutMs()))
                    .onErrorResume(failure -> Mono.just(unavailable(path, failure)))
                    .block();
        } catch (Exception failure) {
            return unavailable(path, failure);
        }
    }

    public BinaryResponse getBinary(String path) {
        if (!properties.isEnabled()) {
            return new BinaryResponse(
                    HttpStatus.SERVICE_UNAVAILABLE.value(),
                    "AgentOS gateway is disabled.".getBytes(StandardCharsets.UTF_8),
                    MediaType.TEXT_PLAIN_VALUE,
                    null
            );
        }
        try {
            return webClient.get().uri(path).exchangeToMono(response -> {
                        int upstreamStatus = response.statusCode().value();
                        String contentType = response.headers().contentType()
                                .map(MediaType::toString)
                                .orElse(MediaType.APPLICATION_OCTET_STREAM_VALUE);
                        String disposition = response.headers().asHttpHeaders()
                                .getFirst(HttpHeaders.CONTENT_DISPOSITION);
                        return response.bodyToMono(byte[].class).defaultIfEmpty(new byte[0])
                                .map(body -> {
                                    if (upstreamStatus >= 500) {
                                        return new BinaryResponse(
                                                HttpStatus.BAD_GATEWAY.value(),
                                                "AgentOS service returned an error."
                                                        .getBytes(StandardCharsets.UTF_8),
                                                MediaType.TEXT_PLAIN_VALUE,
                                                null
                                        );
                                    }
                                    return new BinaryResponse(
                                            upstreamStatus, body, contentType, disposition
                                    );
                                });
                    })
                    .timeout(Duration.ofMillis(properties.getProgressTimeoutMs()))
                    .onErrorReturn(new BinaryResponse(
                            HttpStatus.SERVICE_UNAVAILABLE.value(),
                            "AgentOS gateway unavailable."
                                    .getBytes(StandardCharsets.UTF_8),
                            MediaType.TEXT_PLAIN_VALUE,
                            null
                    ))
                    .block();
        } catch (Exception failure) {
            log.error("AgentOS binary gateway unavailable. path={}, type={}",
                    path, failure.getClass().getSimpleName());
            return new BinaryResponse(
                    HttpStatus.SERVICE_UNAVAILABLE.value(),
                    "AgentOS gateway unavailable."
                            .getBytes(StandardCharsets.UTF_8),
                    MediaType.TEXT_PLAIN_VALUE,
                    null
            );
        }
    }

    private int postTimeoutMs(String path) {
        return path.endsWith("/missions")
                ? properties.getAsyncStartTimeoutMs()
                : properties.getTimeoutMs();
    }

    public Map<String, Object> postMultipart(String path, MultipartFile file) {
        if (!properties.isEnabled()) {
            return error(HttpStatus.SERVICE_UNAVAILABLE.value(), "AGENTOS_GATEWAY_DISABLED",
                    "AgentOS gateway is disabled.");
        }
        try {
            MultipartBodyBuilder builder = new MultipartBodyBuilder();
            MediaType contentType;
            try {
                contentType = MediaType.parseMediaType(
                        file.getContentType() == null ? MediaType.APPLICATION_OCTET_STREAM_VALUE : file.getContentType()
                );
            } catch (IllegalArgumentException ignored) {
                contentType = MediaType.APPLICATION_OCTET_STREAM;
            }
            builder.part("file", file.getResource())
                    .filename(file.getOriginalFilename() == null ? "attachment" : file.getOriginalFilename())
                    .contentType(contentType);
            return webClient.post().uri(path)
                    .contentType(MediaType.MULTIPART_FORM_DATA)
                    .body(BodyInserters.fromMultipartData(builder.build()))
                    .exchangeToMono(response -> mapResponse(response.statusCode().value(), response.bodyToMono(String.class)))
                    .timeout(Duration.ofMillis(properties.getProgressTimeoutMs()))
                    .onErrorResume(failure -> Mono.just(unavailable(path, failure)))
                    .block();
        } catch (Exception failure) {
            return unavailable(path, failure);
        }
    }

    private int getTimeoutMs(String path) {
        String pathWithoutQuery = path == null ? "" : path.split("\\?", 2)[0];
        return (AgentOsPaths.UPSTREAM_ROOT + "/missions").equals(pathWithoutQuery)
                ? properties.getTimeoutMs()
                : properties.getProgressTimeoutMs();
    }

    private Mono<Map<String, Object>> mapResponse(int upstreamStatus, Mono<String> responseBody) {
        return responseBody.defaultIfEmpty("").map(body -> {
            if (upstreamStatus >= 200 && upstreamStatus < 300) {
                Map<String, Object> parsed = parseObject(body);
                parsed.put(INTERNAL_HTTP_STATUS_KEY, upstreamStatus);
                return parsed;
            }
            if (upstreamStatus >= 400 && upstreamStatus < 500) {
                Map<String, Object> parsed = parseObject(body);
                Object code = parsed.get("code");
                Object message = parsed.get("message");
                Object requestId = parsed.get("requestId");
                if (code instanceof String stableCode && message instanceof String stableMessage) {
                    return error(upstreamStatus, stableCode, sanitize(stableMessage),
                            requestId instanceof String value ? value : null);
                }
                return error(upstreamStatus, "AGENTOS_REQUEST_REJECTED",
                        "AgentOS request was rejected (HTTP " + upstreamStatus + ").", null);
            }
            return error(HttpStatus.BAD_GATEWAY.value(), "AGENTOS_UPSTREAM_ERROR",
                    "AgentOS service returned an error.");
        });
    }

    private Map<String, Object> unavailable(String path, Throwable failure) {
        log.error("AgentOS gateway unavailable. path={}, type={}", path, failure.getClass().getSimpleName());
        return error(HttpStatus.SERVICE_UNAVAILABLE.value(), "AGENTOS_UPSTREAM_UNAVAILABLE",
                "AgentOS gateway unavailable.");
    }

    private <T extends AgentOsApiResponse> Mono<TypedResponse<T>> typedResponse(
            int upstreamStatus,
            Mono<String> responseBody,
            Class<T> responseType
    ) {
        return responseBody.defaultIfEmpty("").map(body -> {
            if (upstreamStatus >= 200 && upstreamStatus < 300) {
                try {
                    return new TypedResponse<>(
                            upstreamStatus,
                            OBJECT_MAPPER.readValue(body, responseType),
                            null
                    );
                } catch (Exception failure) {
                    log.error("Invalid AgentOS success contract. type={}", responseType.getSimpleName());
                    return typedError(HttpStatus.BAD_GATEWAY.value(), "AGENTOS_CONTRACT_INVALID",
                            "AgentOS service returned an invalid response.", null);
                }
            }
            if (upstreamStatus >= 400 && upstreamStatus < 500) {
                try {
                    AgentOsErrorResponse error = OBJECT_MAPPER.readValue(body, AgentOsErrorResponse.class);
                    if (error.code() == null || error.message() == null) {
                        throw new IllegalArgumentException("missing stable error fields");
                    }
                    return new TypedResponse<>(upstreamStatus, null, new AgentOsErrorResponse(
                            error.code(), sanitize(error.message()), error.requestId()
                    ));
                } catch (Exception ignored) {
                    return typedError(upstreamStatus, "AGENTOS_REQUEST_REJECTED",
                            "AgentOS request was rejected (HTTP " + upstreamStatus + ").", null);
                }
            }
            return typedError(HttpStatus.BAD_GATEWAY.value(), "AGENTOS_UPSTREAM_ERROR",
                    "AgentOS service returned an error.", null);
        });
    }

    private <T extends AgentOsApiResponse> TypedResponse<T> typedUnavailable(String path, Throwable failure) {
        log.error("AgentOS gateway unavailable. path={}, type={}", path, failure.getClass().getSimpleName());
        return typedError(HttpStatus.SERVICE_UNAVAILABLE.value(), "AGENTOS_UPSTREAM_UNAVAILABLE",
                "AgentOS gateway unavailable.", null);
    }

    private <T extends AgentOsApiResponse> TypedResponse<T> typedError(
            int status, String code, String message, String requestId
    ) {
        return new TypedResponse<>(status, null, new AgentOsErrorResponse(code, message, requestId));
    }

    private Map<String, Object> error(int status, String code, String message) {
        return error(status, code, message, null);
    }

    private Map<String, Object> error(int status, String code, String message, String requestId) {
        Map<String, Object> result = new HashMap<>();
        result.put("code", code);
        result.put("message", message);
        if (requestId != null && !requestId.isBlank()) {
            result.put("requestId", requestId);
        }
        result.put(INTERNAL_HTTP_STATUS_KEY, status);
        return result;
    }

    private String sanitize(String value) {
        String sanitized = value.replaceAll("[\\r\\n\\t]", " ").trim();
        return sanitized.substring(0, Math.min(sanitized.length(), 300));
    }

    private Map<String, Object> parseObject(String body) {
        if (body == null || body.isBlank()) {
            return new HashMap<>();
        }
        try {
            return new HashMap<>(OBJECT_MAPPER.readValue(body, new TypeReference<Map<String, Object>>() { }));
        } catch (Exception ignored) {
            return new HashMap<>();
        }
    }
}
