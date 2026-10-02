package com.kinlin.ai.observability;

import io.micrometer.core.instrument.MeterRegistry;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.actuate.observability.AutoConfigureObservability;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.web.reactive.function.client.WebClient;
import com.kinlin.ai.util.JwtUtil;

import java.time.Duration;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * J1.4C §七/§十九：/actuator/prometheus exposition 契约。
 *
 * <p>真实 Spring 上下文 + 真实 Prometheus 暴露序列化器，逐族断言指标线在位：
 * JVM、HTTP ingress、Hikari 连接池、Java→Python 出站、SSE 流生命周期。
 * {@code @AutoConfigureObservability} 必不可少——Boot 3.2 起 @SpringBootTest
 * 默认禁用 metrics export（DisableObservabilityContextCustomizer 注入
 * management.defaults.metrics.export.enabled=false），与生产行为不同，
 * 必须显式打开才能验证 exposition。</p>
 *
 * <p>cache（cache.gets 等）仅在 cache.type=redis 的上下文存在，
 * 由 {@code RoleCacheRedisIntegrationTest} 在真实 Redis 上下文验证。</p>
 */
@SpringBootTest
@AutoConfigureMockMvc
@AutoConfigureObservability
@ActiveProfiles("test")
class ObservabilityExpositionTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private JwtUtil jwtUtil;

    @Autowired
    private MeterRegistry meterRegistry;

    @Autowired
    private ObjectProvider<WebClient> webClient;

    @Test
    void prometheusEndpointExposesCoreMetricFamilies() throws Exception {
        // 先打一笔真实 controller 请求，http_server_requests/api.requests 才会物化
        mockMvc.perform(get("/health")).andExpect(status().isOk());

        MvcResult result = mockMvc.perform(get("/actuator/prometheus")
                        .header("Authorization", "Bearer " + jwtUtil.generateToken(UUID.randomUUID(), "metrics-probe")))
                .andExpect(status().isOk())
                .andReturn();
        String body = result.getResponse().getContentAsString();

        assertFamily(body, "jvm_memory_used_bytes", "JVM 内存");
        // GC 断言用分配计数器（累积 counter，启动即稳定输出）——
        // jvm_gc_pause_seconds 是事件型 timer，测试 JVM 未发生 GC 时无输出行
        assertFamily(body, "jvm_gc_memory_allocated_bytes_total", "GC 分配");
        assertFamily(body, "jvm_threads_live_threads", "线程");
        assertFamily(body, "http_server_requests_seconds", "HTTP ingress");
        assertFamily(body, "hikaricp_connections_active", "Hikari 活跃连接");
        assertFamily(body, "hikaricp_connections_idle", "Hikari 空闲连接");
        assertFamily(body, "hikaricp_connections_pending", "Hikari 等待");
        assertFamily(body, "kinlin_sse_streams_active", "SSE 在流 gauge");
        assertFamily(body, "api_requests", "MetricsService 自有计数");
        assertTrue(meterRegistry.getClass().getName().contains("Prometheus"),
                "metrics export 打开后注册表必须是 PrometheusMeterRegistry: " + meterRegistry.getClass().getName());
    }

    /**
     * 出站指标低基数维度实测：向死端口发一次真实请求（connection refused），
     * family/outcome/status 三维必须以固定词表落地——不依赖源码阅读。
     */
    @Test
    void outboundMetricsCarryLowCardinalityDimensionTags() {
        try {
            webClient.getObject().get().uri("http://127.0.0.1:1/health")
                    .retrieve()
                    .toBodilessEntity()
                    .block(Duration.ofSeconds(2));
        } catch (Exception expected) {
            // 连接失败是本测试的触发器
        }
        assertTrue(meterRegistry.find("kinlin.python.outbound.requests")
                        .tag("family", "health")
                        .tag("outcome", "connection_error")
                        .tag("status", "none")
                        .counters().size() >= 1,
                "出站指标必须携带 family/outcome/status 低基数维度");
    }

    private static void assertFamily(String body, String metric, String label) {
        assertTrue(body.contains(metric), "prometheus 缺失 " + label + " 指标: " + metric);
    }
}
