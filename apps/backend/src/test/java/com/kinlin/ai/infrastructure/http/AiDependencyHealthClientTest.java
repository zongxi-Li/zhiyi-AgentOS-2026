package com.kinlin.ai.infrastructure.http;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.web.reactive.function.client.WebClient;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.Executors;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Characterizes the Python dependency health probe (J1.1 §13): bounded blocking probe,
 * REACHABLE with upstream detail, DEGRADED with exception simple name on failure.
 */
class AiDependencyHealthClientTest {

    private HttpServer server;
    private String baseUrl;

    @BeforeEach
    void startServer() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.setExecutor(Executors.newCachedThreadPool());
        server.createContext("/health/dependencies", exchange -> {
            byte[] bytes = "{\"python\":\"ok\"}".getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, bytes.length);
            exchange.getResponseBody().write(bytes);
            exchange.close();
        });
        server.createContext("/health/slow", exchange -> {
            try {
                Thread.sleep(500);
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
            }
            byte[] bytes = "{}".getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200, bytes.length);
            exchange.getResponseBody().write(bytes);
            exchange.close();
        });
        server.start();
        baseUrl = "http://127.0.0.1:" + server.getAddress().getPort();
    }

    @AfterEach
    void stopServer() {
        server.stop(0);
    }

    @Test
    void reportsReachableWithUpstreamDetail() {
        AiDependencyHealthClient client = client(new PythonServiceProperties(), baseUrl);

        AiDependencyHealthClient.AiDependencyHealth health = client.probe();

        assertEquals("REACHABLE", health.status());
        assertTrue(String.valueOf(health.detail()).contains("python"));
        assertNull(health.errorType());
    }

    @Test
    void reportsDegradedWithSimpleErrorTypeWhenUnreachable() {
        PythonServiceProperties properties = new PythonServiceProperties();
        properties.setUrl("http://127.0.0.1:1");
        AiDependencyHealthClient client = client(properties, "http://127.0.0.1:1");

        AiDependencyHealthClient.AiDependencyHealth health = client.probe();

        assertEquals("DEGRADED", health.status());
        assertNull(health.detail());
        assertTrue(health.errorType() != null && !health.errorType().isBlank());
    }

    @Test
    void boundsTheProbeWaitWithTheHealthTimeout() {
        PythonServiceProperties properties = new PythonServiceProperties();
        properties.setHealthTimeout(50);
        AiDependencyHealthClient slowClient = new AiDependencyHealthClient(
                WebClient.builder().baseUrl(baseUrl + "/health/slow").build(), properties);

        AiDependencyHealthClient.AiDependencyHealth health = slowClient.probe();

        assertEquals("DEGRADED", health.status());
    }

    private AiDependencyHealthClient client(PythonServiceProperties properties, String url) {
        return new AiDependencyHealthClient(WebClient.builder().baseUrl(url).build(), properties);
    }
}
