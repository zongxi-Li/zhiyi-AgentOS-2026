package com.kinlin.ai.integration;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.Disposable;

import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * INT-2F-4B：真实 PostgreSQL 持久会话权威下的 SSE 撤销（pg-it + loopback 上游）。
 *
 * <p>与 H2 端到端互补：会话行与 revoked_at 落在真实 PG（Flyway V11 迁移产物），
 * SSE 复核与 HTTP 认证共享同一权威。核心三断言：有效交付、撤销终止、重连 401。
 * pg-it 此前不出站调用，无 ai.internal.token——本类注入 test 同款非生产内部令牌。</p>
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = "ai.internal.token=test-only-internal-token-0123456789abcdef")
class SseSessionRevocationPostgresTest extends PostgresIntegrationTestBase {

    private static HttpServer upstream;
    private static ExecutorService upstreamExecutor;

    @LocalServerPort
    private int port;

    @Autowired
    private ObjectMapper objectMapper;

    @BeforeAll
    static void startUpstream() throws Exception {
        upstream = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        upstreamExecutor = Executors.newCachedThreadPool();
        upstream.setExecutor(upstreamExecutor);
        upstream.createContext("/", exchange -> {
            exchange.getResponseHeaders().set("Content-Type", "text/event-stream");
            exchange.sendResponseHeaders(200, 0);
            try (OutputStream out = exchange.getResponseBody()) {
                while (true) {
                    out.write("event: model.output.delta\ndata: {\"seq\":1}\n\n"
                            .getBytes(StandardCharsets.UTF_8));
                    out.flush();
                    Thread.sleep(200);
                }
            } catch (Exception disconnect) {
                // 撤销取消上游订阅：正常断开
            }
        });
        upstream.start();
    }

    @AfterAll
    static void stopUpstream() {
        upstream.stop(0);
        upstreamExecutor.shutdownNow();
    }

    @DynamicPropertySource
    static void pointPythonTransportAtLoopback(DynamicPropertyRegistry registry) {
        registry.add("ai.service.url", () -> "http://127.0.0.1:" + upstream.getAddress().getPort());
    }

    private WebClient client() {
        return WebClient.builder().baseUrl("http://127.0.0.1:" + port).build();
    }

    private String registerToken() throws Exception {
        String body = client().post().uri("/auth/register")
                .contentType(MediaType.APPLICATION_JSON)
                .bodyValue("{\"username\":\"pgsse_" + UUID.randomUUID().toString().replace("-", "").substring(0, 9)
                        + "\",\"password\":\"pass-123456\"}")
                .retrieve()
                .bodyToMono(String.class)
                .block(Duration.ofSeconds(10));
        return objectMapper.readTree(body).get("token").asText();
    }

    @Test
    void postgresBackedSessionRevocationStopsStreamAndRejectsReconnect() throws Exception {
        String token = registerToken();

        List<ServerSentEvent<String>> received = new CopyOnWriteArrayList<>();
        CountDownLatch invalidated = new CountDownLatch(1);
        Disposable subscription = client().get()
                .uri("/api/agentos/v2/runs/" + UUID.randomUUID() + "/events")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
                .accept(MediaType.TEXT_EVENT_STREAM)
                .retrieve()
                .bodyToFlux(new org.springframework.core.ParameterizedTypeReference<ServerSentEvent<String>>() { })
                .subscribe(event -> {
                    received.add(event);
                    if ("auth.invalidated".equals(event.event())) {
                        invalidated.countDown();
                    }
                });

        long deadline = System.currentTimeMillis() + 10_000;
        while (received.size() < 2 && System.currentTimeMillis() < deadline) {
            Thread.sleep(50);
        }
        assertThat(received).hasSizeGreaterThanOrEqualTo(2);

        long logoutStartedAt = System.nanoTime();
        client().post().uri("/auth/logout")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
                .retrieve()
                .toBodilessEntity()
                .block(Duration.ofSeconds(10));

        assertThat(invalidated.await(15, TimeUnit.SECONDS)).isTrue();
        long elapsedMs = (System.nanoTime() - logoutStartedAt) / 1_000_000;
        subscription.dispose();

        assertThat(elapsedMs).as("PG 权威下撤销→终止 ≤5000ms").isLessThanOrEqualTo(5_000);
        System.out.println("[INT-2F-4B] postgres-backed revocation→invalidated elapsedMs=" + elapsedMs);
        assertThat(received.get(received.size() - 1).event()).isEqualTo("auth.invalidated");

        // 撤销后重连必须被真实认证拒绝
        Integer status = client().get().uri("/api/agentos/v2/runs/" + UUID.randomUUID() + "/events")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
                .exchangeToMono(response -> reactor.core.publisher.Mono.just(response.statusCode().value()))
                .block(Duration.ofSeconds(10));
        assertThat(status).isEqualTo(401);
    }
}
