package com.kinlin.ai.config;

import com.kinlin.ai.gateway.AiGatewayHeaders;
import com.kinlin.ai.gateway.PythonServiceAuthentication;
import com.kinlin.ai.gateway.TrustedUserContextForwarder;
import com.kinlin.ai.infrastructure.http.PythonClientFactory;
import com.kinlin.ai.infrastructure.http.PythonServiceProperties;
import com.kinlin.ai.infrastructure.http.TransportErrorClassifier;
import com.kinlin.ai.observability.TraceContext;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.reactive.function.client.ClientRequest;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;
import io.netty.channel.ChannelOption;
import reactor.netty.http.client.HttpClient;

import java.util.concurrent.TimeUnit;

/**
 * Shared Java-to-Python WebClient builder: the single choke point where service
 * authentication, trusted identity, trace propagation and outbound transport metrics
 * are attached. Base URL and per-category timeouts live in
 * {@link PythonServiceProperties}; clients built from this builder must not
 * re-configure authentication themselves.
 */
@Configuration
public class WebClientConfig {

    @Bean
    public WebClient.Builder webClientBuilder(
            PythonServiceAuthentication authentication,
            TrustedUserContextForwarder userContextForwarder,
            PythonServiceProperties properties,
            MeterRegistry meterRegistry
    ) {
        HttpClient httpClient = HttpClient.create()
                .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, properties.getConnectTimeout());
        return WebClient.builder()
                .clientConnector(new ReactorClientHttpConnector(httpClient))
                .codecs(configurer -> configurer
                        .defaultCodecs()
                        // Trace payloads grow with long-running missions; keep
                        // the gateway from converting a valid run into a 503.
                        .maxInMemorySize(50 * 1024 * 1024)) // 50MB
                .defaultHeader("Content-Type", "application/json")
                .filter((request, next) -> {
                    ClientRequest authenticated = ClientRequest.from(request)
                            .headers(headers -> {
                                authentication.apply(headers);
                                if (!headers.containsKey(TraceContext.HEADER)) {
                                    headers.set(TraceContext.HEADER, TraceContext.currentTraceId());
                                }
                                if (!request.url().getPath().startsWith("/health")
                                        && !headers.containsKey(AiGatewayHeaders.AUTHENTICATED_USER_ID)) {
                                    userContextForwarder.apply(headers);
                                }
                            })
                            .build();
                    long start = System.nanoTime();
                    return next.exchange(authenticated)
                            .doOnSuccess(response -> record(meterRegistry, request,
                                    response == null ? null : response.statusCode().value(), start, null))
                            .doOnError(error -> record(meterRegistry, request, null, start, error))
                            .doOnCancel(() -> record(meterRegistry, request, null, start, null));
                });
    }

    @Bean
    public WebClient webClient(PythonClientFactory factory) {
        return factory.pythonTransport();
    }

    private static void record(
            MeterRegistry registry,
            ClientRequest request,
            Integer status,
            long startNanos,
            Throwable error
    ) {
        String family = PythonClientFactory.endpointFamily(request.url().getPath());
        String outcome;
        String statusTag;
        if (error != null) {
            outcome = TransportErrorClassifier.isTimeout(error) ? "timeout"
                    : TransportErrorClassifier.isConnectionFailure(error) ? "connection_error" : "error";
            statusTag = "none";
        } else if (status == null) {
            outcome = "cancelled";
            statusTag = "none";
        } else {
            outcome = "response";
            statusTag = String.valueOf(status);
        }
        registry.counter("kinlin.python.outbound.requests",
                        "family", family, "outcome", outcome, "status", statusTag)
                .increment();
        registry.timer("kinlin.python.outbound.duration",
                        "family", family, "outcome", outcome)
                .record(System.nanoTime() - startNanos, TimeUnit.NANOSECONDS);
    }
}
