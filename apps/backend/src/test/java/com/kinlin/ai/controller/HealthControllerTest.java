package com.kinlin.ai.controller;

import com.kinlin.ai.client.AiDependencyHealthClient;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

import static org.mockito.Mockito.mock;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class HealthControllerTest {

    private MockMvc mockMvc;
    private final AtomicReference<AiDependencyHealthClient.AiDependencyHealth> probeResult =
            new AtomicReference<>(AiDependencyHealthClient.AiDependencyHealth.reachable(Map.of("python", "up")));

    @BeforeEach
    void setUp() {
        AiDependencyHealthClient delegatingClient = new AiDependencyHealthClient() {
            @Override
            public AiDependencyHealth probe() {
                return probeResult.get();
            }
        };
        HealthController controller = new HealthController(
                mock(JdbcTemplate.class),
                mock(RedisConnectionFactory.class),
                delegatingClient
        );
        mockMvc = MockMvcBuilders.standaloneSetup(controller).build();
    }

    @Test
    void exposesTheCanonicalBackendServiceName() throws Exception {
        mockMvc.perform(get("/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.service").value("kinlin-backend"));

        mockMvc.perform(get("/health/live"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.service").value("kinlin-backend"));
    }

    @Test
    void reportsReachablePythonDependencyWithoutAffectingReadiness() throws Exception {
        mockMvc.perform(get("/health/dependencies"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("REACHABLE"))
                .andExpect(jsonPath("$.dependencies.aiService.status").value("REACHABLE"))
                .andExpect(jsonPath("$.dependencies.aiService.affectsReadiness").value(false));
    }

    @Test
    void reportsDegradedPythonDependencyWithSimpleErrorType() throws Exception {
        probeResult.set(AiDependencyHealthClient.AiDependencyHealth.degraded("ConnectException"));

        mockMvc.perform(get("/health/dependencies"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("DEGRADED"))
                .andExpect(jsonPath("$.dependencies.aiService.error").value("ConnectException"))
                .andExpect(jsonPath("$.dependencies.aiService.affectsReadiness").value(false));
    }
}
