package com.kinlin.ai.gateway;

import com.kinlin.ai.security.AuthenticatedUserContext;
import com.kinlin.ai.service.LoginSessionService;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.ResponseEntity;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Flux;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * INT-2F-4B：SSE 网关会话撤销合同（真实 loopback HTTP 上游 + 真实时钟短参数）。
 *
 * <p>短参数（P=80ms/Q=300ms/L=250ms）把 3s/1s/5s 生产合同压缩到亚秒级，
 * 验证行为与终止事件语义；真实生产参数的端到端计时在
 * {@code SseSessionRevocationEndToEndTest} 覆盖。</p>
 */
class AiSseGatewaySessionRevocationTest {

    private static final long PERIOD_MS = 80;
    private static final long QUERY_TIMEOUT_MS = 300;
    private static final long LEASE_MS = 250;

    private HttpServer server;
    private ExecutorService serverExecutor;
    private final LoginSessionService loginSessionService = mock(LoginSessionService.class);
    private final AtomicBoolean sessionActive = new AtomicBoolean(true);
    private final AtomicLong upstreamSent = new AtomicLong();
    private SimpleMeterRegistry registry;

    @BeforeEach
    void startServer() throws IOException {
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(
                        new AuthenticatedUserContext(UUID.randomUUID(), "sse-rev", "USER",
                                UUID.randomUUID(), null, null),
                        null, List.of()));
        when(loginSessionService.isSessionActive(any(), any()))
                .thenAnswer(invocation -> sessionActive.get());

        // 持续事件流：每 40ms 一条带序号的 delta，用于证明撤销后不再交付
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        serverExecutor = Executors.newCachedThreadPool();
        server.setExecutor(serverExecutor);
        server.createContext("/ai/live", exchange -> {
            respondStreamHeaders(exchange);
            try (OutputStream out = exchange.getResponseBody()) {
                while (true) {
                    long seq = upstreamSent.incrementAndGet();
                    out.write(("event: model.output.delta\ndata: {\"seq\":" + seq + "}\n\n")
                            .getBytes(StandardCharsets.UTF_8));
                    out.flush();
                    Thread.sleep(40);
                }
            } catch (IOException | InterruptedException ignored) {
                // 客户端断开（撤销取消）或测试关闭：正常退出
            }
        });
        // 空闲流：建立后不发送任何事件，直到客户端断开
        server.createContext("/ai/silent", exchange -> {
            respondStreamHeaders(exchange);
            try (OutputStream out = exchange.getResponseBody()) {
                while (true) {
                    Thread.sleep(50);
                    out.write(": keepalive\n\n".getBytes(StandardCharsets.UTF_8));
                    out.flush();
                }
            } catch (IOException | InterruptedException ignored) {
            }
        });
        server.start();
    }

    @AfterEach
    void stopServer() {
        server.stop(0);
        serverExecutor.shutdownNow();
        SecurityContextHolder.clearContext();
    }

    private void respondStreamHeaders(HttpExchange exchange) throws IOException {
        exchange.getResponseHeaders().set("Content-Type", "text/event-stream");
        exchange.sendResponseHeaders(200, 0);
    }

    private AiSseGatewayService service() {
        registry = new SimpleMeterRegistry();
        return new AiSseGatewayService(
                WebClient.builder().baseUrl("http://127.0.0.1:" + server.getAddress().getPort()).build(),
                10_000, 60_000, PERIOD_MS, QUERY_TIMEOUT_MS, LEASE_MS,
                new TrustedUserContextForwarder(), loginSessionService, registry);
    }

    private static String dataOf(ServerSentEvent<String> event) {
        return event.data() == null ? "" : event.data();
    }

    @Test
    void activeSessionDeliversProtectedEventsUninterrupted() {
        ResponseEntity<Flux<ServerSentEvent<String>>> response =
                service().openGet("/ai/live").block(Duration.ofSeconds(2));
        assertThat(response.getStatusCode().value()).isEqualTo(200);

        List<ServerSentEvent<String>> events = response.getBody()
                .take(10)
                .collectList()
                .block(Duration.ofSeconds(5));

        assertThat(events).hasSize(10);
        assertThat(events).allSatisfy(e -> assertThat(e.event()).isEqualTo("model.output.delta"));
        assertThat(events).noneMatch(e -> "auth.invalidated".equals(e.event()));
    }

    @Test
    void revocationStopsDeliveryAndEmitsTerminalInvalidatedEvent() throws InterruptedException {
        ResponseEntity<Flux<ServerSentEvent<String>>> response =
                service().openGet("/ai/live").block(Duration.ofSeconds(2));

        // 单次订阅持续收集（WebClient 流体只允许订阅一次）
        List<ServerSentEvent<String>> received = new java.util.concurrent.CopyOnWriteArrayList<>();
        java.util.concurrent.CountDownLatch invalidated = new java.util.concurrent.CountDownLatch(1);
        reactor.core.Disposable subscription = response.getBody().subscribe(
                event -> {
                    received.add(event);
                    if ("auth.invalidated".equals(event.event())) {
                        invalidated.countDown();
                    }
                });

        // 撤销前先收到若干受保护事件
        long deadline = System.currentTimeMillis() + 5_000;
        while (received.size() < 3 && System.currentTimeMillis() < deadline) {
            Thread.sleep(20);
        }
        assertThat(received).hasSizeGreaterThanOrEqualTo(3);

        long revokeAtNanos = System.nanoTime();
        sessionActive.set(false);

        assertThat(invalidated.await(5, java.util.concurrent.TimeUnit.SECONDS))
                .as("撤销后必须收到 auth.invalidated 终止事件").isTrue();
        long elapsedMs = (System.nanoTime() - revokeAtNanos) / 1_000_000;
        // 终止事件落地后再宽限一个事件周期，确认没有新的受保护事件跟上
        Thread.sleep(120);
        subscription.dispose();

        int lastDeltaIndex = -1;
        int invalidatedIndex = -1;
        for (int i = 0; i < received.size(); i++) {
            String name = received.get(i).event();
            if ("model.output.delta".equals(name)) {
                lastDeltaIndex = i;
            } else if ("auth.invalidated".equals(name)) {
                invalidatedIndex = i;
            }
        }
        assertThat(invalidatedIndex).as("缺少终止事件").isGreaterThanOrEqualTo(0);
        assertThat(lastDeltaIndex).as("终止事件之后不允许出现新的受保护事件")
                .isLessThan(invalidatedIndex);
        assertThat(elapsedMs).as("撤销到终止事件 ≤ P+Q+余量（生产合同 5s 的压缩版）").isLessThan(2_000);
        assertThat(registry.find("kinlin.sse.streams.session_revoked").counter().count()).isEqualTo(1.0);
    }

    @Test
    void idleStreamTerminatesOnRevocationWithoutBusinessEvents() throws InterruptedException {
        ResponseEntity<Flux<ServerSentEvent<String>>> response =
                service().openGet("/ai/silent").block(Duration.ofSeconds(2));
        assertThat(response.getStatusCode().value()).isEqualTo(200);

        // 先确认流活着（收到注释 keepalive 不会作为事件交付；等待一个复核周期）
        Thread.sleep(150);
        sessionActive.set(false);

        ServerSentEvent<String> terminal = response.getBody()
                .filter(e -> e.event() != null)
                .next()
                .block(Duration.ofSeconds(5));

        assertThat(terminal).isNotNull();
        assertThat(terminal.event()).isEqualTo("auth.invalidated");
    }

    @Test
    void sessionlessContextCannotOpenProtectedStream() {
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(
                        new AuthenticatedUserContext(UUID.randomUUID(), "legacy", "USER", null, null, null),
                        null, List.of()));

        ResponseEntity<Flux<ServerSentEvent<String>>> response =
                service().openGet("/ai/live").block(Duration.ofSeconds(2));

        assertThat(response.getStatusCode().value()).isEqualTo(401);
        ServerSentEvent<String> body = response.getBody().next().block(Duration.ofSeconds(2));
        assertThat(dataOf(body)).contains("AI_STREAM_SESSION_REQUIRED");
    }

    @Test
    void queryFailureFailsClosedWithTerminalEvent() {
        when(loginSessionService.isSessionActive(any(), any()))
                .thenThrow(new org.springframework.dao.DataAccessResourceFailureException("db down"));

        ResponseEntity<Flux<ServerSentEvent<String>>> response =
                service().openGet("/ai/live").block(Duration.ofSeconds(2));

        ServerSentEvent<String> terminal = response.getBody()
                .take(5)
                .filter(e -> e.event() != null && !"model.output.delta".equals(e.event()))
                .next()
                .block(Duration.ofSeconds(5));

        assertThat(terminal).isNotNull();
        assertThat(terminal.event()).isEqualTo("auth.invalidated");
    }

    // 撤销后重连的拒绝发生在 filter（真实 401），由 SseSessionRevocationEndToEndTest
    // .revokedSessionCannotReconnect 覆盖；网关级不重复该链路（建连初租期放行
    // filter 已认证的观测属设计语义）。
}
