package com.kinlin.ai.performance;

import com.kinlin.ai.entity.Conversation;
import com.kinlin.ai.entity.Message;
import com.kinlin.ai.integration.PostgresContainerBase;
import com.kinlin.ai.integration.RedisIntegrationTestBase;
import com.kinlin.ai.repository.ConversationRepository;
import com.kinlin.ai.repository.MessageRepository;
import com.kinlin.ai.repository.RoleRepository;
import com.kinlin.ai.repository.UserRepository;
import com.kinlin.ai.entity.Role;
import jakarta.persistence.EntityManagerFactory;
import org.hibernate.SessionFactory;
import org.hibernate.stat.Statistics;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.MethodOrderer;
import org.junit.jupiter.api.Order;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestMethodOrder;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.actuate.observability.AutoConfigureObservability;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.ApplicationContext;
import org.springframework.core.env.Environment;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

import java.io.IOException;
import java.io.OutputStream;
import java.lang.management.ManagementFactory;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.DoubleAdder;
import java.util.concurrent.atomic.LongAdder;

/**
 * J1.4C §九~十四：系统级性能基线（真实 HTTP、真实 PostgreSQL/Redis、
 * deterministic fake Python upstream）。
 *
 * <p>运行方式（普通 {@code mvn test} 不运行本类——surefire excludedGroups=performance，
 * 由 -Pperformance profile 打开）：</p>
 * <pre>mvn test -Pperformance -Dtest=KinlinBackendBaselineBenchmark -Dkinlin.perf=true</pre>
 *
 * <p>§十 隔离外部模型变量：全部 Java→Python 出站走本类内置 fake upstream
 * （固定 ~8KB JSON 响应 + 固定 15ms 延迟），不依赖 GLM/OpenAI/公网工具，
 * 测的是 Java 自身 transport/serialization/persistence/cache overhead。</p>
 *
 * <p>§十三 Load Profile：并发 1→10→25→50 逐级；50 级若 error rate 或
 * Hikari pending 明显恶化即记录饱和点，不强行跑 100。</p>
 */
@Tag("performance")
@EnabledIfSystemProperty(named = "kinlin.perf", matches = "true")
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureObservability
@TestMethodOrder(MethodOrderer.OrderAnnotation.class)
class KinlinBackendBaselineBenchmark extends RedisIntegrationTestBase {

    private static final int[] CONCURRENCY_LEVELS = {1, 10, 25, 50};
    private static final int WARMUP_SECONDS = 5;
    private static final int MEASURE_SECONDS = 10;

    /** §十：确定性 fake Python upstream（固定响应体 + 固定延迟，零外部依赖）。 */
    private static final FakeUpstream FAKE_UPSTREAM = new FakeUpstream();

    @LocalServerPort
    private int port;

    @Autowired
    private EntityManagerFactory entityManagerFactory;

    @Autowired
    private Environment environment;

    @Autowired
    private ApplicationContext applicationContext;

    @Autowired
    private io.micrometer.core.instrument.MeterRegistry meterRegistry;

    private final HttpClient http = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(5))
            .build();

    private String token;
    private String builtinRoleId;
    private String baseUrl;
    private String username;

    @DynamicPropertySource
    static void fakeUpstream(DynamicPropertyRegistry registry) {
        FAKE_UPSTREAM.start();
        registry.add("ai.service.url", () -> "http://127.0.0.1:" + FAKE_UPSTREAM.port());
        registry.add("ai.internal.token", () -> "benchmark-only-internal-token-0123456789abcdef");
        // 基准测的是基础设施开销；应用默认 300/min 限流会把 c≥10 全部打成 429
        //（首轮基线实测 errorRate=1.0），benchmark 上下文内放开
        registry.add("app.rate-limit.requests-per-minute", () -> "10000000");
    }

    @AfterAll
    static void stopFake() {
        FAKE_UPSTREAM.stop();
    }

    // ------------------------------------------------------------------
    // §九 Workloads（每条：逐级并发，warmup→measure，P50/P95/P99/max/吞吐/错误率）
    // ------------------------------------------------------------------

    @Test
    @Order(0)
    void environmentAndWorkloads() {
        recordEnvironment();
        prepareBenchmarkData();

        runWorkload("W1-auth-login", () -> post("/auth/login",
                "{\"username\":\"" + username + "\",\"password\":\"Bench#2026\"}", null));
        runWorkload("W2-role-read", () -> get("/roles/" + builtinRoleId));
        runWorkload("W3-conversation-list", () -> get("/conversations"));
        runWorkload("W4-chat-persistence", () -> post("/chat/text",
                "{\"text\":\"benchmark 消息 " + UUID.randomUUID() + "\"}", token));
        runWorkload("W5-agentos-gateway", () -> get("/api/agentos/v2/missions"));

        // §十一 cache hit ratio（W2 期间由 CacheConfig 窄仪表累计）
        double hits = counter("cache.gets", "result", "hit");
        double misses = counter("cache.gets", "result", "miss");
        System.out.printf("[CACHE] gets hit=%.0f miss=%.0f hitRatio=%.2f errors=%.0f puts=%.0f evictions=%.0f%n",
                hits, misses, hits / Math.max(1, hits + misses),
                counter("cache.errors"), counter("cache.puts"), counter("cache.evictions"));
    }

    private void prepareBenchmarkData() {
        baseUrl = "http://127.0.0.1:" + port;
        username = "bench_" + UUID.randomUUID().toString().substring(0, 8);
        HttpResponse<String> register = post("/auth/register",
                "{\"username\":\"" + username + "\",\"password\":\"Bench#2026\",\"email\":\""
                        + username + "@example.com\"}", null);
        if (register.statusCode() >= 400) {
            throw new IllegalStateException("register failed: " + register.statusCode() + " " + register.body());
        }
        HttpResponse<String> login = post("/auth/login",
                "{\"username\":\"" + username + "\",\"password\":\"Bench#2026\"}", null);
        token = extractJsonString(login.body(), "token");

        UUID userId = applicationContext.getBean(UserRepository.class)
                .findByUsername(username).orElseThrow().getId();

        var roles = applicationContext.getBean(RoleRepository.class)
                .findByRoleType(Role.RoleType.BUILTIN);
        builtinRoleId = roles.get(0).getId().toString();

        ConversationRepository conversationRepository =
                applicationContext.getBean(ConversationRepository.class);
        MessageRepository messageRepository = applicationContext.getBean(MessageRepository.class);
        for (int i = 0; i < 10; i++) {
            Conversation conversation = new Conversation();
            conversation.setUserId(userId);
            conversation.setContextId("bench_" + UUID.randomUUID());
            conversation.setWorkspaceMode("chat");
            Conversation saved = conversationRepository.saveAndFlush(conversation);
            for (int m = 0; m < 4; m++) {
                Message message = new Message();
                message.setConversationId(saved.getId());
                message.setRole(m % 2 == 0 ? Message.MessageRole.USER : Message.MessageRole.ASSISTANT);
                message.setContent("bench 消息 " + m + "：" + "x".repeat(120));
                messageRepository.saveAndFlush(message);
            }
        }
        System.out.println("[ENV] benchmark user/conversations/role seeded");
    }

    // ------------------------------------------------------------------
    // load driver
    // ------------------------------------------------------------------

    private void runWorkload(String name, HttpCall request) {
        System.out.printf("%n[WORKLOAD] %s%n", name);
        for (int concurrency : CONCURRENCY_LEVELS) {
            drive(name, request, concurrency, WARMUP_SECONDS, false);
            LoadResult result = drive(name, request, concurrency, MEASURE_SECONDS, true);
            System.out.printf("[LEVEL %2d] P50=%6.1fms P95=%7.1fms P99=%7.1fms max=%8.1fms "
                            + "throughput=%7.1f rps errorRate=%.3f cpu=%.2f hikariPending=%d%n",
                    concurrency, result.p50, result.p95, result.p99, result.max,
                    result.throughputRps, result.errorRate, result.cpuLoad, result.hikariPendingMax);
            if (concurrency == 50 && (result.errorRate > 0.01 || result.hikariPendingMax > 0)) {
                System.out.println("[SATURATION] 50 并发已现恶化信号（errorRate/pending），§十三不强行跑 100");
                return;
            }
        }
    }

    private LoadResult drive(String name, HttpCall request,
                             int concurrency, int seconds, boolean collect) {
        ExecutorService pool = Executors.newFixedThreadPool(concurrency);
        CountDownLatch startLatch = new CountDownLatch(1);
        AtomicBoolean running = new AtomicBoolean(true);
        LongAdder requests = new LongAdder();
        LongAdder errors = new LongAdder();
        List<List<Long>> latencies = Collections.synchronizedList(new ArrayList<>());
        DoubleAdder cpuSum = new DoubleAdder();
        AtomicLong cpuSamples = new AtomicLong();
        AtomicLong hikariPendingMax = new AtomicLong();
        Statistics statistics = entityManagerFactory.unwrap(SessionFactory.class).getStatistics();
        long queriesBefore = statistics.getPrepareStatementCount();
        long httpBefore = httpRequestsSnapshot();

        com.sun.management.OperatingSystemMXBean os =
                (com.sun.management.OperatingSystemMXBean) ManagementFactory.getOperatingSystemMXBean();
        Thread sampler = new Thread(() -> {
            while (running.get()) {
                try {
                    cpuSum.add(Math.max(0, os.getProcessCpuLoad()));
                    cpuSamples.incrementAndGet();
                    var pending = meterRegistry.find("hikaricp.connections.pending").gauge();
                    if (pending != null) {
                        hikariPendingMax.accumulateAndGet((long) Math.ceil(pending.value()), Math::max);
                    }
                    Thread.sleep(500);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    return;
                }
            }
        });
        sampler.setDaemon(true);
        sampler.start();

        List<Thread> workers = new ArrayList<>();
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(seconds);
        for (int i = 0; i < concurrency; i++) {
            List<Long> local = collect ? Collections.synchronizedList(new ArrayList<>()) : null;
            if (local != null) {
                latencies.add(local);
            }
            Thread worker = new Thread(() -> {
                try {
                    startLatch.await();
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    return;
                }
                while (running.get()) {
                    long start = System.nanoTime();
                    boolean failed = false;
                    try {
                        HttpResponse<String> response = (HttpResponse<String>) request.call();
                        failed = response.statusCode() >= 400;
                    } catch (Exception e) {
                        failed = true;
                    }
                    if (local != null) {
                        local.add((System.nanoTime() - start) / 1_000_000);
                    }
                    if (failed) {
                        errors.increment();
                    }
                    requests.increment();
                    if (System.nanoTime() > deadline) {
                        running.set(false);
                    }
                }
            }, name + "-c" + concurrency + "-" + i);
            workers.add(worker);
            worker.start();
        }
        startLatch.countDown();
        for (Thread worker : workers) {
            try {
                worker.join(TimeUnit.SECONDS.toMillis(seconds + 30));
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }
        running.set(false);

        LoadResult result = new LoadResult();
        List<Long> all = new ArrayList<>();
        latencies.forEach(all::addAll);
        all.sort(Comparator.naturalOrder());
        if (!all.isEmpty()) {
            result.p50 = percentile(all, 0.50);
            result.p95 = percentile(all, 0.95);
            result.p99 = percentile(all, 0.99);
            result.max = all.get(all.size() - 1);
        }
        result.errorRate = requests.sum() == 0 ? 0 : (double) errors.sum() / requests.sum();
        result.throughputRps = requests.sum() / (double) seconds;
        result.cpuLoad = cpuSamples.get() == 0 ? 0 : cpuSum.sum() / cpuSamples.get();
        result.hikariPendingMax = hikariPendingMax.get();
        result.queriesPerRequest = requests.sum() == 0 ? 0
                : (statistics.getPrepareStatementCount() - queriesBefore)
                    / (double) Math.max(1, requests.sum());
        System.out.printf("[DETAIL %s c=%d] requests=%d statements=%d (≈%.2f query/request) "
                        + "http-server-delta=%d%n",
                name, concurrency, requests.sum(),
                statistics.getPrepareStatementCount() - queriesBefore,
                result.queriesPerRequest, httpRequestsSnapshot() - httpBefore);
        return result;
    }

    private long httpRequestsSnapshot() {
        return (long) meterRegistry.find("http.server.requests").timers().stream()
                .mapToDouble(t -> t.count()).sum();
    }

    private double counter(String name) {
        return meterRegistry.find(name).counters().stream()
                .mapToDouble(c -> c.count()).sum();
    }

    private double counter(String name, String tagKey, String tagValue) {
        return meterRegistry.find(name).counters().stream()
                .filter(c -> tagValue.equals(c.getId().getTag(tagKey)))
                .mapToDouble(c -> c.count()).sum();
    }

    private static double percentile(List<Long> sorted, double p) {
        int index = (int) Math.ceil(p * sorted.size()) - 1;
        return sorted.get(Math.max(0, Math.min(sorted.size() - 1, index)));
    }

    private void recordEnvironment() {
        System.out.println("=================================================================");
        System.out.println("[ENV] os=" + System.getProperty("os.name") + " " + System.getProperty("os.arch"));
        System.out.println("[ENV] java=" + System.getProperty("java.version")
                + " (" + System.getProperty("java.vm.name") + ")");
        var osBean = (com.sun.management.OperatingSystemMXBean) ManagementFactory.getOperatingSystemMXBean();
        System.out.printf("[ENV] cpu-cores=%d max-heap=%dMB%n",
                osBean.getAvailableProcessors(), Runtime.getRuntime().maxMemory() / 1024 / 1024);
        System.out.println("[ENV] postgres=" + PostgresContainerBase.POSTGRES.getDockerImageName()
                + " redis=" + RedisIntegrationTestBase.REDIS.getDockerImageName());
        System.out.printf("[ENV] warmup=%ds measure=%ds levels=%s cache=%s%n",
                WARMUP_SECONDS, MEASURE_SECONDS, Arrays.toString(CONCURRENCY_LEVELS),
                environment.getProperty("spring.cache.type"));
        System.out.println("[ENV] fake-upstream=固定 ~8KB JSON / 固定 15ms 延迟（无外部 LLM）");
        System.out.println("=================================================================");
    }

    // ------------------------------------------------------------------
    // HTTP helpers
    // ------------------------------------------------------------------

    private HttpResponse<String> get(String path) {
        return send(HttpRequest.newBuilder()
                .uri(URI.create(baseUrl + path))
                .header("Authorization", "Bearer " + token)
                .GET()
                .build());
    }

    private HttpResponse<String> post(String path, String body, String authToken) {
        HttpRequest.Builder builder = HttpRequest.newBuilder()
                .uri(URI.create(baseUrl + path))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(body, StandardCharsets.UTF_8));
        if (authToken != null) {
            builder.header("Authorization", "Bearer " + authToken);
        }
        return send(builder.build());
    }

    private HttpResponse<String> send(HttpRequest request) {
        try {
            return http.send(request, HttpResponse.BodyHandlers.ofString());
        } catch (IOException e) {
            throw new RuntimeException(e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new RuntimeException(e);
        }
    }

    private static String extractJsonString(String body, String field) {
        int keyIndex = body.indexOf("\"" + field + "\"");
        if (keyIndex < 0) {
            throw new IllegalStateException("field not found: " + field + " in " + body);
        }
        int colon = body.indexOf(':', keyIndex);
        int quoteOpen = body.indexOf('"', colon);
        int quoteClose = body.indexOf('"', quoteOpen + 1);
        return body.substring(quoteOpen + 1, quoteClose);
    }

    private static final class LoadResult {
        double p50;
        double p95;
        double p99;
        double max;
        double throughputRps;
        double errorRate;
        double cpuLoad;
        double queriesPerRequest;
        long hikariPendingMax;
    }

    private interface HttpCall {
        HttpResponse<String> call() throws Exception;
    }

    /** 固定响应 fake：/ai/chat/text（chat persistence）、/ai/agentos/v2/**（gateway）。 */
    private static final class FakeUpstream {
        private com.sun.net.httpserver.HttpServer server;
        // AiChatClient 真实契约：ChatResponse.text（首轮基线 W4 全 500 的教训：
        // 用了 content 字段名 → assistant 消息 content=null 撞 NOT NULL）
        private static final String CHAT_BODY =
                "{\"text\":\"" + "固定回复。".repeat(300) + "\",\"confidence\":0.9}";
        private static final String MISSIONS_BODY =
                "[" + ("{\"id\":\"m\",\"goal\":\"g\",\"status\":\"COMPLETED\"},").repeat(60) + "]";

        void start() {
            if (server != null) {
                return;
            }
            try {
                server = com.sun.net.httpserver.HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
                server.setExecutor(Executors.newFixedThreadPool(64));
                respondWith(server, "/ai/chat/text", CHAT_BODY);
                respondWith(server, "/ai/agentos/v2/missions", MISSIONS_BODY);
                respondWith(server, "/rag/query", "{\"chunks\":[]}");
                server.start();
            } catch (IOException e) {
                throw new IllegalStateException(e);
            }
        }

        private void respondWith(com.sun.net.httpserver.HttpServer httpServer, String path, String body) {
            httpServer.createContext(path, exchange -> {
                try {
                    exchange.getRequestBody().readAllBytes();
                    byte[] payload = body.getBytes(StandardCharsets.UTF_8);
                    exchange.getResponseHeaders().set("Content-Type", "application/json");
                    Thread.sleep(15); // 固定上游延迟（§十）
                    exchange.sendResponseHeaders(200, payload.length);
                    try (OutputStream out = exchange.getResponseBody()) {
                        out.write(payload);
                    }
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                } finally {
                    exchange.close();
                }
            });
        }

        int port() {
            return server.getAddress().getPort();
        }

        void stop() {
            if (server != null) {
                server.stop(0);
                server = null;
            }
        }
    }
}
