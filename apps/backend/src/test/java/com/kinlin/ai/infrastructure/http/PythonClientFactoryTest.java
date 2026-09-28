package com.kinlin.ai.infrastructure.http;

import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.web.reactive.function.client.ClientRequest;
import org.springframework.web.reactive.function.client.ClientResponse;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.net.URI;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;

/**
 * Characterizes the canonical Python base-url ownership (J1.1 §7/§19-H): the factory is
 * the only place where the Python root is resolved from configuration, and every formal
 * client transport is rooted there.
 */
class PythonClientFactoryTest {

    @Test
    void rootsTheSharedTransportAtTheCanonicalPythonServiceUrl() {
        AtomicReference<URI> seen = new AtomicReference<>();
        WebClient.Builder shared = WebClient.builder().exchangeFunction(request -> {
            seen.set(request.url());
            return Mono.just(ClientResponse.create(HttpStatus.OK)
                    .header("Content-Type", "application/json")
                    .body("{}")
                    .build());
        });
        PythonServiceProperties properties = new PythonServiceProperties();
        properties.setUrl("http://127.0.0.1:65500");

        WebClient transport = new PythonClientFactory(shared, properties).pythonTransport();

        transport.get().uri("/health/dependencies")
                .retrieve().bodyToMono(String.class).block();
        assertEquals("http://127.0.0.1:65500/health/dependencies", String.valueOf(seen.get()));
    }

    @Test
    void keepsCanonicalDefaultsForDeploymentCompatibility() {
        PythonServiceProperties properties = new PythonServiceProperties();

        assertEquals("http://localhost:8000", properties.getUrl());
        assertEquals(15000, properties.getConnectTimeout());
        assertEquals(240000, properties.getTimeout());
        assertEquals(3000, properties.getHealthTimeout());
    }

    @Test
    void classifiesEndpointFamiliesForTransportMetrics() {
        assertEquals("agentos", PythonClientFactory.endpointFamily("/ai/agentos/v2/runs"));
        assertEquals("health", PythonClientFactory.endpointFamily("/health/dependencies"));
        assertEquals("platform_rag", PythonClientFactory.endpointFamily("/rag/query"));
        assertEquals("platform_knowledge_graph",
                PythonClientFactory.endpointFamily("/api/knowledge-graph/build"));
        assertEquals("platform_proxy", PythonClientFactory.endpointFamily("/ai/chat/text"));
        assertEquals("other", PythonClientFactory.endpointFamily("/something/else"));
        assertEquals("other", PythonClientFactory.endpointFamily(null));
    }

    @Test
    void doesNotMutateTheSharedBuilderAcrossTransports() {
        AtomicReference<URI> seen = new AtomicReference<>();
        WebClient.Builder shared = WebClient.builder().exchangeFunction((ClientRequest request) -> {
            seen.set(request.url());
            return Mono.just(ClientResponse.create(HttpStatus.OK).body("{}").build());
        });
        PythonServiceProperties properties = new PythonServiceProperties();
        properties.setUrl("http://127.0.0.1:65501");

        WebClient first = new PythonClientFactory(shared, properties).pythonTransport();

        // The shared builder stays un-rooted: transports built from it carry no base URL.
        shared.build().get().uri("/isolated").retrieve().bodyToMono(String.class).block();
        assertEquals("/isolated", String.valueOf(seen.get()));

        // The factory transport is rooted at the canonical URL.
        first.get().uri("/probe").retrieve().bodyToMono(String.class).block();
        assertEquals("http://127.0.0.1:65501/probe", String.valueOf(seen.get()));
    }
}
