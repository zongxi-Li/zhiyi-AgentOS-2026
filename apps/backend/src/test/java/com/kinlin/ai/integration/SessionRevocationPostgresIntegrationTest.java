package com.kinlin.ai.integration;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.util.JwtUtil;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * INT-2F-4A：隔离 PostgreSQL 上的 Flyway V11 迁移与会话撤销持久化行为。
 *
 * <p>真实 Testcontainers PostgreSQL + Flyway migrate + Hibernate validate
 * （上下文启动即双关卡）；HTTP 注册/登录/登出后用 JdbcTemplate 直查
 * iam_login_sessions 表的真实行——证明撤销是持久事实，不是内存状态。</p>
 */
@SpringBootTest
@AutoConfigureMockMvc
class SessionRevocationPostgresIntegrationTest extends PostgresIntegrationTestBase {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Autowired
    private JwtUtil jwtUtil;

    private String uniqueUsername() {
        return "pg_" + UUID.randomUUID().toString().replace("-", "").substring(0, 12);
    }

    @Test
    void flywayCreatedSessionTableWithContractColumns() {
        // V11 迁移产物：表与核心列必须存在（上下文启动已过 migrate+validate 双关卡）
        Integer columnCount = jdbcTemplate.queryForObject(
                "select count(*) from information_schema.columns "
                        + "where table_schema = 'public' and table_name = 'iam_login_sessions' "
                        + "and column_name in ('sid','user_id','created_at','expires_at','revoked_at')",
                Integer.class);
        assertThat(columnCount).isEqualTo(5);
    }

    @Test
    void loginAndLogoutPersistRealRowsInPostgres() throws Exception {
        String username = uniqueUsername();

        // 注册 + 登录各创建一行持久会话
        String registerToken = authPost("/auth/register", username);
        String loginToken = authPost("/auth/login", username);
        UUID registerSid = jwtUtil.getSidFromToken(registerToken);
        UUID loginSid = jwtUtil.getSidFromToken(loginToken);
        assertThat(registerSid).isNotEqualTo(loginSid);

        Integer loginRows = jdbcTemplate.queryForObject(
                "select count(*) from iam_login_sessions where sid in (?, ?)",
                Integer.class, registerSid, loginSid);
        assertThat(loginRows).isEqualTo(2);

        // 登出登录会话：revoked_at 落库且只写这一行
        mockMvc.perform(post("/auth/logout")
                        .header("Authorization", "Bearer " + loginToken))
                .andExpect(status().isNoContent());

        Integer revokedRows = jdbcTemplate.queryForObject(
                "select count(*) from iam_login_sessions where sid in (?, ?) and revoked_at is not null",
                Integer.class, registerSid, loginSid);
        assertThat(revokedRows).isEqualTo(1);
        java.sql.Timestamp revokedAt = jdbcTemplate.queryForObject(
                "select revoked_at from iam_login_sessions where sid = ?", java.sql.Timestamp.class, loginSid);
        assertThat(revokedAt).isNotNull();

        // 撤销后的旧 JWT 在真实 PG 会话权威下被拒绝；未撤销会话仍有效
        mockMvc.perform(get("/users/me")
                        .header("Authorization", "Bearer " + loginToken))
                .andExpect(status().isUnauthorized());
        mockMvc.perform(get("/users/me")
                        .header("Authorization", "Bearer " + registerToken))
                .andExpect(status().is2xxSuccessful());
    }

    /** 注册/登录 POST，返回响应中的 token。 */
    private String authPost(String path, String username) throws Exception {
        MvcResult result = mockMvc.perform(post(path)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"" + username + "\",\"password\":\"pass-123456\"}"))
                .andExpect(status().isOk())
                .andReturn();
        JsonNode body = objectMapper.readTree(result.getResponse().getContentAsString());
        return body.get("token").asText();
    }
}
