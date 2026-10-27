package com.kinlin.ai.security;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.controller.UserController;
import com.kinlin.ai.entity.LoginSession;
import com.kinlin.ai.repository.LoginSessionRepository;
import com.kinlin.ai.util.JwtUtil;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import java.util.Optional;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * INT-2F-4A：数据库无法确认会话状态时的 fail-closed 行为。
 *
 * <p>会话权威（LoginSessionRepository）被 mock 为抛 DataAccessException：
 * 认证期必须 503 且不进入业务 Controller；登录期会话创建失败必须 503 且
 * 不返回 Token；撤销期失败必须 503，不得伪装成功。</p>
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class SessionStateUnavailableTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private JwtUtil jwtUtil;

    @MockBean
    private LoginSessionRepository loginSessionRepository;

    /** 业务链路哨兵：503 的请求必须连 Controller 都不进。 */
    @MockBean
    private UserController userController;

    private static final DataAccessResourceFailureException DB_DOWN =
            new DataAccessResourceFailureException("db down");

    private String uniqueUsername() {
        return "su_" + UUID.randomUUID().toString().replace("-", "").substring(0, 12);
    }

    private String registerAndGetToken(String username) throws Exception {
        // save 透传参数实体：sid/userId 与真实签发一致
        when(loginSessionRepository.save(any())).thenAnswer(inv -> inv.getArgument(0));

        MvcResult result = mockMvc.perform(post("/auth/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"" + username + "\",\"password\":\"pass-123456\"}"))
                .andExpect(status().isOk())
                .andReturn();
        return objectMapper.readTree(result.getResponse().getContentAsString()).get("token").asText();
    }

    private LoginSession activeSession(UUID sid, UUID userId) {
        LoginSession session = new LoginSession();
        session.setSid(sid);
        session.setUserId(userId);
        session.setCreatedAt(java.time.LocalDateTime.now().minusMinutes(1));
        session.setExpiresAt(java.time.LocalDateTime.now().plusHours(1));
        return session;
    }

    @Test
    void authFailsClosedWith503WhenSessionStateUnavailable() throws Exception {
        String token = registerAndGetToken(uniqueUsername());
        UUID sid = jwtUtil.getSidFromToken(token);

        when(loginSessionRepository.findBySid(sid)).thenThrow(DB_DOWN);

        mockMvc.perform(get("/users/" + UUID.randomUUID())
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isServiceUnavailable())
                .andExpect(jsonPath("$.error").value("auth_state_unavailable"));

        // 数据库无法确认会话状态：不进入受保护业务链路
        verifyNoInteractions(userController);
    }

    @Test
    void loginReturns503WithoutTokenWhenSessionPersistFails() throws Exception {
        // 先注册一个真实用户（save 正常），再让登录会话创建失败
        String username = uniqueUsername();
        registerAndGetToken(username);

        when(loginSessionRepository.save(any())).thenThrow(DB_DOWN);

        MvcResult result = mockMvc.perform(post("/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"" + username + "\",\"password\":\"pass-123456\"}"))
                .andExpect(status().isServiceUnavailable())
                .andReturn();
        JsonNode body = objectMapper.readTree(
                result.getResponse().getContentAsString(java.nio.charset.StandardCharsets.UTF_8));
        assertThat(body.hasNonNull("token")).isFalse();
        assertThat(body.get("message").asText()).isEqualTo("登录服务暂不可用，请稍后重试");
    }

    @Test
    void logoutReturns503AndKeepsSessionWhenRevokeFails() throws Exception {
        String token = registerAndGetToken(uniqueUsername());
        UUID sid = jwtUtil.getSidFromToken(token);
        UUID userId = jwtUtil.getUserIdFromToken(token);

        when(loginSessionRepository.findBySid(sid)).thenReturn(Optional.of(activeSession(sid, userId)));
        when(loginSessionRepository.revokeBySid(any(), any())).thenThrow(DB_DOWN);

        mockMvc.perform(post("/auth/logout")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isServiceUnavailable());

        // 撤销失败后：会话仍有效，同一 Token 仍可访问（不能伪装成已撤销成功）
        org.mockito.Mockito.when(userController.getUser(userId))
                .thenReturn(org.springframework.http.ResponseEntity.notFound().build());
        mockMvc.perform(get("/users/" + userId)
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isNotFound()); // 到达 mock 业务 Controller = 认证仍通过
    }
}
