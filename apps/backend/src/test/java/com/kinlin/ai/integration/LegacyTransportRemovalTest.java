package com.kinlin.ai.integration;

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
 * J1.3 characterization：legacy transport 已整体移除，路由必须不复存在。
 *
 * <ul>
 *   <li>{@code /ws}（SockJS/STOMP endpoint，WebSocketConfig 已删除）→ 404</li>
 *   <li>{@code /api/agent/{role}/chat}（legacy role chat，AgentController +
 *       legacy/agent 链已删除）→ 404</li>
 * </ul>
 *
 * <p>正式替代路径：Chat 走 REST（ChatController），AgentOS 走 Mission/Run
 * （/api/agentos/v2/**），运行事件走 SSE（AgentOsEventController）。</p>
 */
@SpringBootTest
@AutoConfigureMockMvc(addFilters = false)
@ActiveProfiles("test")
class LegacyTransportRemovalTest {

    @Autowired
    private MockMvc mockMvc;

    @Test
    void wsEndpointIsNoLongerMapped() throws Exception {
        mockMvc.perform(get("/ws")).andExpect(status().isNotFound());
        mockMvc.perform(get("/ws/info")).andExpect(status().isNotFound());
    }

    @Test
    void legacyRoleChatRoutesAreNoLongerMapped() throws Exception {
        for (String role : new String[]{"lawyer", "teacher", "programmer", "writer"}) {
            mockMvc.perform(post("/api/agent/" + role + "/chat")
                            .contentType("application/json")
                            .content("{\"text\":\"hi\"}"))
                    .andExpect(status().isNotFound());
        }
    }
}
