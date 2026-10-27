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
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import java.time.LocalDateTime;
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoMoreInteractions;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * INT-2F-4A：持久会话状态与业务链路进入验证（H2 快速面）。
 *
 * <p>与 {@code SessionRevocationHttpContractTest} 的差异：本类直接断言
 * 会话表的真实持久状态（sid 行、revoked_at 单向事实），并用 mock 的
 * UserController 证明撤销后的请求没有进入受保护业务链路——不是只看 401。</p>
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class SessionRevocationPersistenceTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private JwtUtil jwtUtil;

    @Autowired
    private LoginSessionRepository loginSessionRepository;

    /** 业务链路哨兵：撤销后的请求必须连 Controller 都不进。 */
    @MockBean
    private UserController userController;

    private String uniqueUsername() {
        return "sp_" + UUID.randomUUID().toString().replace("-", "").substring(0, 12);
    }

    private record Account(String token, UUID userId, UUID sid, String username) {
    }

    private Account register(String username) throws Exception {
        MvcResult result = mockMvc.perform(post("/auth/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"" + username + "\",\"password\":\"pass-123456\"}"))
                .andExpect(status().isOk())
                .andReturn();
        JsonNode body = objectMapper.readTree(result.getResponse().getContentAsString());
        String token = body.get("token").asText();
        return new Account(token, UUID.fromString(body.get("userId").asText()),
                jwtUtil.getSidFromToken(token), username);
    }

    @Test
    void loginPersistsSessionRowBoundToUser() throws Exception {
        String username = uniqueUsername();
        mockMvc.perform(post("/auth/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"" + username + "\",\"password\":\"pass-123456\"}"))
                .andExpect(status().isOk());

        MvcResult loginResult = mockMvc.perform(post("/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"" + username + "\",\"password\":\"pass-123456\"}"))
                .andExpect(status().isOk())
                .andReturn();
        String token = objectMapper.readTree(loginResult.getResponse().getContentAsString()).get("token").asText();
        UUID sid = jwtUtil.getSidFromToken(token);

        // 真实持久状态：登录创建独立会话行（注册一行 + 登录一行）
        List<LoginSession> sessions = loginSessionRepository.findAll();
        assertThat(sessions).anySatisfy(session -> {
            assertThat(session.getSid()).isEqualTo(sid);
            assertThat(session.getUserId()).isNotNull();
            assertThat(session.getRevokedAt()).isNull();
            assertThat(session.getExpiresAt()).isAfter(LocalDateTime.now());
        });
    }

    @Test
    void failedPasswordCreatesNoSession() throws Exception {
        String username = uniqueUsername();
        mockMvc.perform(post("/auth/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"" + username + "\",\"password\":\"pass-123456\"}"))
                .andExpect(status().isOk());
        long before = loginSessionRepository.count();

        mockMvc.perform(post("/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"" + username + "\",\"password\":\"wrong-password\"}"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.token").doesNotExist());

        assertThat(loginSessionRepository.count()).isEqualTo(before);
    }

    @Test
    void revokedJwtNeverReachesProtectedController() throws Exception {
        Account account = register(uniqueUsername());

        // 撤销前：请求真实进入业务 Controller（stub 404，只关心是否到达）
        org.mockito.Mockito.when(userController.getUser(account.userId()))
                .thenReturn(org.springframework.http.ResponseEntity.notFound().build());
        mockMvc.perform(get("/users/" + account.userId())
                        .header("Authorization", "Bearer " + account.token()))
                .andExpect(status().isNotFound());
        verify(userController).getUser(account.userId());

        mockMvc.perform(post("/auth/logout")
                        .header("Authorization", "Bearer " + account.token()))
                .andExpect(status().isNoContent());

        // 真实持久状态：revoked_at 已写入且单向
        LoginSession session = loginSessionRepository.findById(account.sid()).orElseThrow();
        assertThat(session.getRevokedAt()).isNotNull();

        // 撤销后：同 JWT 请求受保护路由，业务 Controller 零新增调用
        mockMvc.perform(get("/users/" + account.userId())
                        .header("Authorization", "Bearer " + account.token()))
                .andExpect(status().isUnauthorized());
        verifyNoMoreInteractions(userController);
    }

    @Test
    void sessionExpiryDisablesTokenEvenWithoutLogout() throws Exception {
        Account account = register(uniqueUsername());

        org.mockito.Mockito.when(userController.getUser(account.userId()))
                .thenReturn(org.springframework.http.ResponseEntity.notFound().build());
        mockMvc.perform(get("/users/" + account.userId())
                        .header("Authorization", "Bearer " + account.token()))
                .andExpect(status().isNotFound());

        // 直接把会话行改为已过期（模拟跨天后的自然到期，无需撤销）
        LoginSession session = loginSessionRepository.findById(account.sid()).orElseThrow();
        session.setExpiresAt(LocalDateTime.now().minusMinutes(1));
        loginSessionRepository.save(session);

        mockMvc.perform(get("/users/" + account.userId())
                        .header("Authorization", "Bearer " + account.token()))
                .andExpect(status().isUnauthorized());
    }
}
