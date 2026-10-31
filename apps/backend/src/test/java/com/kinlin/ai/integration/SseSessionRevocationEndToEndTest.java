package com.kinlin.ai.integration;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import io.micrometer.core.instrument.MeterRegistry;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.Disposable;
import reactor.core.publisher.Flux;

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
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.ConcurrentHashMap;
import java.util.Map;
import reactor.core.publisher.SignalType;

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;

/**
 * INT-2F-4B：真实网络 SSE 会话撤销端到端（生产参数 3s/1s/5s）。
 *
 * <p>链路：测试 WebClient →（真实 HTTP）→ Java RANDOM_PORT 真实过滤器链 +
 * AuthController/AgentOsEventController/AiSseGatewayService + 真实 H2 IAM →
 * （真实 HTTP）→ loopback 事件源。测量 logout 请求发出至 auth.invalidated
 * 到达的真实墙钟，断言 ≤5s 取消上界；不用虚拟时钟。</p>
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@ActiveProfiles("test")
class SseSessionRevocationEndToEndTest {

    private static HttpServer upstream;
    private static ExecutorService upstreamExecutor;
    private static final AtomicLong SEQUENCE = new AtomicLong();
    private static final Map<String, CountDownLatch> UPSTREAM_CLOSED = new ConcurrentHashMap<>();
    private final List<StreamSubscription> openedStreams = new CopyOnWriteArrayList<>();

    @LocalServerPort
    private int port;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private MeterRegistry meterRegistry;

    @BeforeAll
    static void startUpstream() throws Exception {
        upstream = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        upstreamExecutor = Executors.newCachedThreadPool();
        upstream.setExecutor(upstreamExecutor);
        // 受控事件源：每 200ms 一条带唯一序号的受保护事件（持续到客户端断开）
        upstream.createContext("/", exchange -> {
            CountDownLatch closed = UPSTREAM_CLOSED.computeIfAbsent(
                    exchange.getRequestURI().getPath(), ignored -> new CountDownLatch(1));
            exchange.getResponseHeaders().set("Content-Type", "text/event-stream");
            exchange.sendResponseHeaders(200, 0);
            try (OutputStream out = exchange.getResponseBody()) {
                while (true) {
                    long seq = SEQUENCE.incrementAndGet();
                    out.write(("event: model.output.delta\ndata: {\"seq\":" + seq + "}\n\n")
                            .getBytes(StandardCharsets.UTF_8));
                    out.flush();
                    Thread.sleep(200);
                }
            } catch (Exception disconnect) {
                // Java 网关撤销后取消上游订阅：正常断开
            } finally {
                closed.countDown();
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

    private record Account(String token, String userId, String username) {
    }

    private WebClient client() {
        return WebClient.builder().baseUrl("http://127.0.0.1:" + port).build();
    }

    private Account register() throws Exception {
        String body = client().post().uri("/auth/register")
                .contentType(MediaType.APPLICATION_JSON)
                .bodyValue("{\"username\":\"e2e_" + UUID.randomUUID().toString().replace("-", "").substring(0, 10)
                        + "\",\"password\":\"pass-123456\"}")
                .retrieve()
                .bodyToMono(String.class)
                .block(Duration.ofSeconds(10));
        JsonNode node = objectMapper.readTree(body);
        return new Account(node.get("token").asText(), node.get("userId").asText(), node.get("username").asText());
    }

    private void logout(Account account) {
        client().post().uri("/auth/logout")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + account.token())
                .retrieve()
                .toBodilessEntity()
                .block(Duration.ofSeconds(10));
    }

    private record StreamSubscription(
            List<ServerSentEvent<String>> received,
            CountDownLatch invalidated,
            CountDownLatch terminated,
            AtomicReference<SignalType> terminalSignal,
            AtomicReference<Throwable> failure,
            String upstreamPath,
            Disposable subscription) {
    }

    /** 打开真实 SSE 流并持续收集事件；invalidated latch 在收到终止事件时放开。 */
    private StreamSubscription openStream(Account account, String runId) throws InterruptedException {
        List<ServerSentEvent<String>> received = new CopyOnWriteArrayList<>();
        CountDownLatch invalidated = new CountDownLatch(1);
        CountDownLatch connected = new CountDownLatch(1);
        CountDownLatch terminated = new CountDownLatch(1);
        AtomicReference<SignalType> terminalSignal = new AtomicReference<>();
        AtomicReference<Throwable> failure = new AtomicReference<>();
        String upstreamPath = "/ai/agentos/v2/runs/" + runId + "/events";
        UPSTREAM_CLOSED.put(upstreamPath, new CountDownLatch(1));
        Disposable subscription = client().get()
                .uri("/api/agentos/v2/runs/" + runId + "/events")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + account.token())
                .accept(MediaType.TEXT_EVENT_STREAM)
                .retrieve()
                .bodyToFlux(new org.springframework.core.ParameterizedTypeReference<ServerSentEvent<String>>() { })
                .doFinally(signal -> {
                    terminalSignal.set(signal);
                    terminated.countDown();
                    connected.countDown();
                })
                .subscribe(event -> {
                    received.add(event);
                    if ("model.output.delta".equals(event.event())) {
                        connected.countDown();
                    }
                    if ("auth.invalidated".equals(event.event())) {
                        invalidated.countDown();
                    }
                }, failure::set);
        StreamSubscription stream = new StreamSubscription(received, invalidated, terminated,
                terminalSignal, failure, upstreamPath, subscription);
        openedStreams.add(stream);
        assertThat(connected.await(10, TimeUnit.SECONDS)).as("必须先建立真实 SSE 并交付受保护事件").isTrue();
        assertThat(failure.get()).as("建连不得被 401 或其它错误替代").isNull();
        assertThat(received).anyMatch(event -> "model.output.delta".equals(event.event()));
        return stream;
    }

    @AfterEach
    void closeEveryOpenedStreamAndAwaitGatewayRelease() throws InterruptedException {
        openedStreams.forEach(stream -> stream.subscription().dispose());
        for (StreamSubscription stream : openedStreams) {
            assertThat(stream.terminated().await(5, TimeUnit.SECONDS)).isTrue();
            assertThat(stream.failure().get()).isNull();
        }
        await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> {
            assertThat(activeStreams()).isZero();
            assertThat(counter("opened")).isEqualTo(counter("completed") + counter("cancelled"));
        });
        for (StreamSubscription stream : openedStreams) {
            assertThat(UPSTREAM_CLOSED.remove(stream.upstreamPath()).await(5, TimeUnit.SECONDS))
                    .as("网关结束后必须关闭对应上游 HTTP 流").isTrue();
        }
    }

    private double activeStreams() {
        return meterRegistry.get("kinlin.sse.streams.active").gauge().value();
    }

    private double counter(String suffix) {
        return meterRegistry.find("kinlin.sse.streams." + suffix).counters()
                .stream().mapToDouble(counter -> counter.count()).sum();
    }

    private void awaitCompletion(StreamSubscription stream) throws InterruptedException {
        assertThat(stream.terminated().await(10, TimeUnit.SECONDS)).as("终止事件之后必须完成 HTTP 流").isTrue();
        assertThat(stream.failure().get()).isNull();
        assertThat(stream.terminalSignal().get()).isEqualTo(SignalType.ON_COMPLETE);
    }

    private static String lastEventName(List<ServerSentEvent<String>> received) {
        return received.isEmpty() ? null : received.get(received.size() - 1).event();
    }

    @Test
    void revocationStopsProtectedDeliveryWithinContractBoundOnRealNetwork() throws Exception {
        Account account = register();
        StreamSubscription stream = openStream(account, UUID.randomUUID().toString());

        // 撤销前：真实受保护事件持续交付
        await().atMost(Duration.ofSeconds(10)).untilAsserted(() ->
                assertThat(stream.received()).hasSizeGreaterThanOrEqualTo(3));
        assertThat(stream.received()).hasSizeGreaterThanOrEqualTo(3);

        long logoutStartedAt = System.nanoTime();
        logout(account);

        // 真实墙钟：撤销请求发出 → auth.invalidated 到达 ≤ 5s（P=3s + Q=1s + 余量）
        assertThat(stream.invalidated().await(15, TimeUnit.SECONDS))
                .as("撤销后必须收到终止事件").isTrue();
        long elapsedMs = (System.nanoTime() - logoutStartedAt) / 1_000_000;
        int invalidatedIndex = stream.received().size() - 1;
        awaitCompletion(stream);

        assertThat(elapsedMs).as("撤销→终止真实耗时必须 ≤5000ms").isLessThanOrEqualTo(5_000);
        System.out.println("[INT-2F-4B] real-network revocation→invalidated elapsedMs=" + elapsedMs);
        assertThat(lastEventName(stream.received())).isEqualTo("auth.invalidated");
        // 终止事件之后未再交付受保护事件
        for (int i = invalidatedIndex + 1; i < stream.received().size(); i++) {
            assertThat(stream.received().get(i).event())
                    .as("终止事件后不允许出现受保护事件")
                    .isNotEqualTo("model.output.delta");
        }
        // 计量：撤销终止一次
        assertThat(meterRegistry.find("kinlin.sse.streams.session_revoked").counters()
                .stream().mapToDouble(c -> c.count()).sum()).isGreaterThanOrEqualTo(1.0);
    }

    @Test
    void revokedSessionCannotReconnect() throws Exception {
        Account account = register();
        logout(account);

        Integer status = client().get().uri("/api/agentos/v2/runs/" + UUID.randomUUID() + "/events")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + account.token())
                .exchangeToMono(response -> reactor.core.publisher.Mono.just(response.statusCode().value()))
                .block(Duration.ofSeconds(10));

        assertThat(status).isEqualTo(401);
    }

    @Test
    void revokingOneSessionDoesNotAffectAnotherUsersStream() throws Exception {
        Account alice = register();
        Account bob = register();
        StreamSubscription aliceStream = openStream(alice, UUID.randomUUID().toString());
        StreamSubscription bobStream = openStream(bob, UUID.randomUUID().toString());

        assertThat(aliceStream.received()).isNotEmpty();
        assertThat(bobStream.received()).isNotEmpty();
        int bobBefore = bobStream.received().size();

        logout(alice);

        assertThat(aliceStream.invalidated().await(15, TimeUnit.SECONDS)).isTrue();
        awaitCompletion(aliceStream);
        // 等待至少 8 条实际事件（源每 200ms 一条），而不是固定休眠后猜测连接状态。
        await().atMost(Duration.ofSeconds(10)).untilAsserted(() ->
                assertThat(bobStream.received().size()).isGreaterThanOrEqualTo(bobBefore + 8));
        int bobAfter = bobStream.received().size();
        aliceStream.subscription().dispose();
        bobStream.subscription().dispose();

        assertThat(bobAfter).as("Bob 会话不受 Alice 登出影响").isGreaterThan(bobBefore);
        assertThat(bobStream.invalidated().getCount()).as("Bob 不应收到终止事件").isEqualTo(1);
    }

    @Test
    void repeatedCancelsAndClosesDoNotLeakActiveStreams() throws Exception {
        Account account = register();
        double activeBefore = activeStreams();
        assertThat(activeBefore).isZero();
        double openedBefore = counter("opened");
        double completedBefore = counter("completed");
        double cancelledBefore = counter("cancelled");

        StreamSubscription first = openStream(account, UUID.randomUUID().toString());
        StreamSubscription second = openStream(account, UUID.randomUUID().toString());
        StreamSubscription third = openStream(account, UUID.randomUUID().toString());
        assertThat(activeStreams()).isEqualTo(activeBefore + 3);
        assertThat(counter("opened")).isEqualTo(openedBefore + 3);

        // 多种终止方式：客户端 cancel ×2 + 服务端撤销 ×1
        first.subscription().dispose();
        first.subscription().dispose();
        second.subscription().dispose();
        second.subscription().dispose();
        await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> {
            assertThat(counter("cancelled")).isEqualTo(cancelledBefore + 2);
            assertThat(activeStreams()).isEqualTo(activeBefore + 1);
        });
        logout(account);
        assertThat(third.invalidated().await(15, TimeUnit.SECONDS)).isTrue();
        awaitCompletion(third);

        // 所有流终结后 active gauge 必须回落（订阅/信号双路径不重复扣减、不残留）
        await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> {
            assertThat(activeStreams()).as("active streams 应精确回到撤销前水位").isEqualTo(activeBefore);
            assertThat(counter("completed")).isEqualTo(completedBefore + 1);
            assertThat(counter("cancelled")).isEqualTo(cancelledBefore + 2);
        });
        assertThat(third.received()).filteredOn(event -> "auth.invalidated".equals(event.event())).hasSize(1);
    }
}
