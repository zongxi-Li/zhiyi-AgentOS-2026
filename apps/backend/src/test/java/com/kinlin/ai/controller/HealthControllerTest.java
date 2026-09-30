package com.kinlin.ai.controller;

import com.kinlin.ai.client.AiDependencyHealthClient;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class HealthControllerTest {

    private final AtomicReference<AiDependencyHealthClient.AiDependencyHealth> probeResult =
            new AtomicReference<>(AiDependencyHealthClient.AiDependencyHealth.reachable(Map.of("python", "up")));

    private AiDependencyHealthClient delegatingClient() {
        return new AiDependencyHealthClient() {
            @Override
            public AiDependencyHealth probe() {
                return probeResult.get();
            }
        };
    }

    /** ObjectProvider 替身：等价于容器中恰好存在（或不存在）一个 RedisConnectionFactory。 */
    @SuppressWarnings("unchecked")
    private static ObjectProvider<RedisConnectionFactory> providerOf(RedisConnectionFactory factory) {
        ObjectProvider<RedisConnectionFactory> provider = mock(ObjectProvider.class);
        when(provider.getIfAvailable()).thenReturn(factory);
        return provider;
    }

    private MockMvc mockMvcWith(JdbcTemplate jdbcTemplate, ObjectProvider<RedisConnectionFactory> redis) {
        HealthController controller = new HealthController(jdbcTemplate, redis, delegatingClient());
        return MockMvcBuilders.standaloneSetup(controller).build();
    }

    @Test
    void exposesTheCanonicalBackendServiceName() throws Exception {
        MockMvc mockMvc = mockMvcWith(mock(JdbcTemplate.class), providerOf(mock(RedisConnectionFactory.class)));

        mockMvc.perform(get("/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.service").value("kinlin-backend"));

        mockMvc.perform(get("/health/live"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.service").value("kinlin-backend"));
    }

    @Test
    void reportsReachablePythonDependencyWithoutAffectingReadiness() throws Exception {
        MockMvc mockMvc = mockMvcWith(mock(JdbcTemplate.class), providerOf(mock(RedisConnectionFactory.class)));

        mockMvc.perform(get("/health/dependencies"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("REACHABLE"))
                .andExpect(jsonPath("$.dependencies.aiService.status").value("REACHABLE"))
                .andExpect(jsonPath("$.dependencies.aiService.affectsReadiness").value(false));
    }

    @Test
    void reportsDegradedPythonDependencyWithSimpleErrorType() throws Exception {
        probeResult.set(AiDependencyHealthClient.AiDependencyHealth.degraded("ConnectException"));
        MockMvc mockMvc = mockMvcWith(mock(JdbcTemplate.class), providerOf(mock(RedisConnectionFactory.class)));

        mockMvc.perform(get("/health/dependencies"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("DEGRADED"))
                .andExpect(jsonPath("$.dependencies.aiService.error").value("ConnectException"))
                .andExpect(jsonPath("$.dependencies.aiService.affectsReadiness").value(false));
    }

    /** J1.4B：Redis 自动配置被排除的 profile（dev/test/pg-it）——/ready 不因缺 Redis 工厂而失败。 */
    @Test
    void readyMarksRedisDisabledWhenConnectionFactoryIsAbsent() throws Exception {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        when(jdbcTemplate.queryForObject("SELECT 1", Integer.class)).thenReturn(1);
        MockMvc mockMvc = mockMvcWith(jdbcTemplate, providerOf(null));

        mockMvc.perform(get("/health/ready"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("UP"))
                .andExpect(jsonPath("$.checks.postgres").value(true))
                .andExpect(jsonPath("$.checks.redis").value("disabled"));
    }
}
