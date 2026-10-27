package com.kinlin.ai.security;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.config.JwtProperties;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import java.nio.charset.StandardCharsets;
import java.util.Date;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * INT-2F-4A：IAM 持久会话与 HTTP 撤销合同（H2 快速面）。
 *
 * <p>真实 Spring Security 过滤器链 + 真实 AuthController/UserService/JPA。
 * 核心链路：登录 → 创建持久会话 → 签发含 sid 的 JWT → 请求校验 →
 * 服务端登出 → 原 JWT 失效。断言不只看状态码：撤销后必须连受保护业务
 * 路由（/users/{id}）一起拒绝，并拒绝无 sid 的旧式 JWT。</p>
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class SessionRevocationHttpContractTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private JwtProperties jwtProperties;

    private record Account(String token, String userId, String username) {
    }

    private String uniqueUsername() {
        return "sr_" + UUID.randomUUID().toString().replace("-", "").substring(0, 12);
    }

    private Account register(String username) throws Exception {
        MvcResult result = mockMvc.perform(post("/auth/register")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"" + username + "\",\"password\":\"pass-123456\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.token").isNotEmpty())
                .andReturn();
        JsonNode body = objectMapper.readTree(result.getResponse().getContentAsString());
        return new Account(body.get("token").asText(), body.get("userId").asText(), username);
    }

    private Account login(String username) throws Exception {
        MvcResult result = mockMvc.perform(post("/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"" + username + "\",\"password\":\"pass-123456\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.token").isNotEmpty())
                .andReturn();
        JsonNode body = objectMapper.readTree(result.getResponse().getContentAsString());
        return new Account(body.get("token").asText(), body.get("userId").asText(), username);
    }

    /** 与现行签发同密钥、同 claims 形态，但缺 sid——模拟强切换前的旧 JWT。 */
    private String legacyTokenWithoutSid(UUID userId, String username) {
        return Jwts.builder()
                .claim("userId", userId.toString())
                .claim("username", username)
                .claim("role", "USER")
                .subject(username)
                .issuedAt(new Date())
                .expiration(new Date(System.currentTimeMillis() + 3600_000))
                .signWith(Keys.hmacShaKeyFor(
                        jwtProperties.getSecret().getBytes(StandardCharsets.UTF_8)))
                .compact();
    }

    @Test
    void logoutRevokesCurrentSessionAndOldJwtIsRejected() throws Exception {
        Account account = register(uniqueUsername());

        // 撤销前：受保护业务路由可达
        mockMvc.perform(get("/users/" + account.userId())
                        .header("Authorization", "Bearer " + account.token()))
                .andExpect(status().isOk());

        // 服务端登出
        mockMvc.perform(post("/auth/logout")
                        .header("Authorization", "Bearer " + account.token()))
                .andExpect(status().isNoContent());

        // 同一 JWT 不能再访问受保护接口
        mockMvc.perform(get("/users/" + account.userId())
                        .header("Authorization", "Bearer " + account.token()))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void logoutItselfRequiresAuthentication() throws Exception {
        mockMvc.perform(post("/auth/logout"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void logoutWithoutSidClaimIsRejectedOnProtectedRoutes() throws Exception {
        Account account = register(uniqueUsername());
        String legacyToken = legacyTokenWithoutSid(UUID.fromString(account.userId()), account.username());

        mockMvc.perform(get("/users/" + account.userId())
                        .header("Authorization", "Bearer " + legacyToken))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void revokedJwtCannotLogoutAgain() throws Exception {
        Account account = register(uniqueUsername());

        mockMvc.perform(post("/auth/logout")
                        .header("Authorization", "Bearer " + account.token()))
                .andExpect(status().isNoContent());

        // 重复退出：原 JWT 已撤销，不能再次进入认证
        mockMvc.perform(post("/auth/logout")
                        .header("Authorization", "Bearer " + account.token()))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void independentSessionsOfSameUserDoNotAffectEachOther() throws Exception {
        String username = uniqueUsername();
        register(username);
        Account first = login(username);
        Account second = login(username);

        assertThat(first.token()).isNotEqualTo(second.token());

        mockMvc.perform(post("/auth/logout")
                        .header("Authorization", "Bearer " + first.token()))
                .andExpect(status().isNoContent());

        // 另一会话不受影响
        mockMvc.perform(get("/users/" + second.userId())
                        .header("Authorization", "Bearer " + second.token()))
                .andExpect(status().isOk());
        mockMvc.perform(get("/users/" + first.userId())
                        .header("Authorization", "Bearer " + first.token()))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void verifyReportsRevokedSessionAsInvalid() throws Exception {
        Account account = register(uniqueUsername());

        mockMvc.perform(get("/auth/verify")
                        .header("Authorization", "Bearer " + account.token()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.valid").value(true));

        mockMvc.perform(post("/auth/logout")
                        .header("Authorization", "Bearer " + account.token()))
                .andExpect(status().isNoContent());

        mockMvc.perform(get("/auth/verify")
                        .header("Authorization", "Bearer " + account.token()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.valid").value(false));
    }
}
