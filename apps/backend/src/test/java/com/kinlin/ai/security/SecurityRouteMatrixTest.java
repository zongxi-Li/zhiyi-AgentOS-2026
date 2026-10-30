package com.kinlin.ai.security;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * J1.4B §十一：安全路由矩阵。
 *
 * <p>permitAll 清单逐条与真实端点对表（filter 全开走真实 SecurityFilterChain）：
 * /health、/health/ready、/auth/**、/actuator/health、/swagger-ui、/v3/api-docs；
 * 受保护代表路由未携带凭证必须 401。J1.3 删除的 /ws/** 不得重新出现为公开路由
 * （授权级表征在 {@code WsEndpointAuthorizationTest}，路由级在
 * {@code LegacyTransportRemovalTest}）。</p>
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class SecurityRouteMatrixTest {

    @Autowired
    private MockMvc mockMvc;

    @Test
    void directLocalApiAliasesReachControllersThroughRealSecurity() throws Exception {
        mockMvc.perform(get("/api/health/ready")).andExpect(status().is2xxSuccessful());
        // Empty login reaches request validation (400), rather than an unmapped route or auth rejection.
        mockMvc.perform(post("/api/auth/login").contentType("application/json").content("{}"))
                .andExpect(status().isBadRequest());
        mockMvc.perform(get("/api/roles/builtin")).andExpect(status().isUnauthorized());
        mockMvc.perform(post("/api/auth/logout")).andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/agentos/v2/missions")).andExpect(status().isUnauthorized());
    }

    @Test
    void publicRoutesStayPublicAndHitRealEndpoints() throws Exception {
        // health 组：真实存在（HealthController）
        mockMvc.perform(get("/health")).andExpect(status().is2xxSuccessful());
        mockMvc.perform(get("/health/ready")).andExpect(status().is2xxSuccessful());
        mockMvc.perform(get("/actuator/health")).andExpect(status().is2xxSuccessful());
        // swagger/api-docs 组：webjar 直接 200 服务，非 401 即证明路由放行
        mockMvc.perform(get("/swagger-ui/index.html"))
                .andExpect(status().is2xxSuccessful());
        mockMvc.perform(get("/v3/api-docs")).andExpect(status().is2xxSuccessful());
    }

    @Test
    void unauthenticatedAccessToProtectedRoutesIsUnauthorized() throws Exception {
        // 覆盖 web 业务面与 AgentOS 北向面的代表路由
        mockMvc.perform(get("/roles/builtin")).andExpect(status().isUnauthorized());
        mockMvc.perform(get("/conversations")).andExpect(status().isUnauthorized());
        mockMvc.perform(post("/chat/text")).andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/agentos/v2/missions")).andExpect(status().isUnauthorized());
        // INT-2F-4A：/auth 不再整体放行，logout 必须经过真实认证
        mockMvc.perform(post("/auth/logout")).andExpect(status().isUnauthorized());
    }
}
