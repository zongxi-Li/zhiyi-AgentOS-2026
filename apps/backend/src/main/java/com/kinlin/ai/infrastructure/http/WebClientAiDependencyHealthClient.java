package com.kinlin.ai.infrastructure.http;

import com.kinlin.ai.client.AiDependencyHealthClient;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;

import java.time.Duration;

/**
 * HTTP client implementation of {@link AiDependencyHealthClient}: owns the only
 * health-related outbound call. Semantics are unchanged from the former
 * controller-inline probe: blocking read with a bounded wait, {@code DEGRADED} +
 * exception simple name on any failure.
 */
@Component
public class WebClientAiDependencyHealthClient implements AiDependencyHealthClient {

    private static final String HEALTH_DEPENDENCIES_PATH = "/health/dependencies";

    private final WebClient transport;
    private final PythonServiceProperties properties;

    public WebClientAiDependencyHealthClient(WebClient pythonTransport, PythonServiceProperties properties) {
        this.transport = pythonTransport;
        this.properties = properties;
    }

    @Override
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
