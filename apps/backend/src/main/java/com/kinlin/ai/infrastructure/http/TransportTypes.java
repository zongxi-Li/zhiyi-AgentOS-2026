package com.kinlin.ai.infrastructure.http;

import org.springframework.core.ParameterizedTypeReference;

import java.util.Map;

/**
 * Shared map type token for the platform-AI client implementations. Transport
 * payloads of the dynamic capabilities stay {@code Map} projections (N1.2 owns
 * systematic typing).
 */
final class TransportTypes {

    static final ParameterizedTypeReference<Map<String, Object>> MAP =
            new ParameterizedTypeReference<>() { };

    private TransportTypes() {
    }
}
