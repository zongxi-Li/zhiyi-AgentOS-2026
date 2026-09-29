package com.kinlin.ai.security;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * J1.3 closure characterization：SecurityConfig 不再对 {@code /ws/**} 公开放行。
 *
 * <p>WebSocket/STOMP transport 已在 J1.3 整体删除（见
 * {@code LegacyTransportRemovalTest}，路由级 404）。授权层面必须同步收紧：
 * 未携带凭证访问 {@code /ws/**} 不得越过认证边界，应被
 * {@code anyRequest().authenticated()} 拦截为 401。</p>
 *
 * <p>与路由级测试的区别：本测试不关闭 servlet filter，
 * 走真实 SecurityFilterChain。</p>
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class WsEndpointAuthorizationTest {

    @Autowired
    private MockMvc mockMvc;

    @Test
    void wsEndpointsAreNoLongerPubliclyPermitted() throws Exception {
        mockMvc.perform(get("/ws/info")).andExpect(status().isUnauthorized());
        mockMvc.perform(get("/ws")).andExpect(status().isUnauthorized());
    }

    @Test
    void healthEndpointRemainsPublic() throws Exception {
        mockMvc.perform(get("/health")).andExpect(status().is2xxSuccessful());
    }
}
