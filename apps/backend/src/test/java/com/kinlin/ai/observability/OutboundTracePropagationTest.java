package com.kinlin.ai.observability;

import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.slf4j.MDC;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.web.reactive.function.client.WebClient;

import java.io.IOException;
import java.io.InputStream;
import java.net.InetSocketAddress;
import java.util.UUID;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;

/**
 * J1.4C §二十：trace 贯通第三段——出站传播。
 *
 * <p>HTTP ingress（TraceIdFilterTest：合法保留/非法重生成）→ Java logs（MDC）
 * → Java→Python outbound：当前 MDC trace_id 必须随出站请求头
 * {@code X-Trace-Id} 传播（WebClientConfig 统一 filter）。
 * traceId 不进入任何 metric tag（ArchitectureGuardTest 侧无 tag 引入，gauge/counter
 * 全部无身份维度）。</p>
 */
@SpringBootTest
@ActiveProfiles("test")
class OutboundTracePropagationTest {

    @Autowired
    private WebClient webClient;

    private HttpServer stub;
    private volatile String stubPath;
    private final AtomicReference<String> capturedTraceId = new AtomicReference<>();

    @BeforeEach
    void startStub() throws IOException {
        stub = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        stub.setExecutor(Executors.newSingleThreadExecutor());
        stub.createContext("/", exchange -> {
            capturedTraceId.set(exchange.getRequestHeaders().getFirst(TraceContext.HEADER));
            try (InputStream ignored = exchange.getRequestBody()) {
                exchange.sendResponseHeaders(200, 2);
                exchange.getResponseBody().write("ok".getBytes());
            } finally {
                exchange.close();
            }
        });
        stub.start();
    }

    @AfterEach
    void stopStub() {
        stub.stop(0);
        MDC.clear();
    }

    @Test
    void outboundRequestCarriesCurrentMdcTraceId() {
        String traceId = UUID.randomUUID().toString();
        MDC.put(TraceContext.MDC_KEY, traceId);

        webClient.get()
                .uri("http://127.0.0.1:" + stub.getAddress().getPort() + "/health")
                .retrieve()
                .toBodilessEntity()
                .block(java.time.Duration.ofSeconds(2));

        assertEquals(traceId, capturedTraceId.get(), "出站请求必须携带 MDC 当前 trace_id");
    }
}
