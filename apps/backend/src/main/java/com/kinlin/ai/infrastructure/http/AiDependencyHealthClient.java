package com.kinlin.ai.infrastructure.http;

import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;

import java.time.Duration;

/**
 * Narrow INFRASTRUCTURE health-probe client for the Python dependency.
 *
 * <p>Owns the only health-related outbound call; controllers must not operate transport
 * themselves. Semantics are unchanged from the former controller-inline probe: blocking
 * read with a bounded wait, {@code DEGRADED} + exception simple name on any failure.</p>
 */
@Component
public class AiDependencyHealthClient {

    public record AiDependencyHealth(String status, Object detail, String errorType) {

        public static AiDependencyHealth reachable(Object detail) {
            return new AiDependencyHealth("REACHABLE", detail, null);
        }

        public static AiDependencyHealth degraded(String errorType) {
            return new AiDependencyHealth("DEGRADED", null, errorType);
        }
    }

    private static final String HEALTH_DEPENDENCIES_PATH = "/health/dependencies";

    private final WebClient transport;
    private final PythonServiceProperties properties;

    public AiDependencyHealthClient(WebClient pythonTransport, PythonServiceProperties properties) {
        this.transport = pythonTransport;
        this.properties = properties;
    }

    public AiDependencyHealth probe() {
        try {
            Object body = transport.get()
                    .uri(HEALTH_DEPENDENCIES_PATH)
                    .retrieve()
                    .bodyToMono(Object.class)
                    .block(Duration.ofMillis(properties.getHealthTimeout()));
            return AiDependencyHealth.reachable(body);
        } catch (Exception error) {
            return AiDependencyHealth.degraded(TransportErrorClassifier.describe(error));
        }
    }
}
