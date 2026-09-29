package com.kinlin.ai.integration;

import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.utility.DockerImageName;

/**
 * J1.4A 持久化契约测试基座：整个测试 JVM 共享一个真实 PostgreSQL 容器
 * （singleton container 模式），版本对齐生产镜像
 * （ops/docker/base-images.json: postgres:15.17-alpine）。
 *
 * <p>分层模型（任务书 §十二）：快速测试走 H2（test profile），
 * 持久化契约 / 迁移测试走本基座的真实 PostgreSQL，生产走真实 PostgreSQL。</p>
 *
 * <p>Docker 不可用时的行为：容器启动失败会以 BLOCKED_BY_DOCKER 的
 * IllegalStateException 直接失败——这是显式失败，不是静默 skip
 * （任务书 §十九：Docker 不可用则 J1.4A 不可标 COMPLETE）。</p>
 */
@ActiveProfiles("pg-it")
public abstract class PostgresIntegrationTestBase {

    /**
     * 生产对齐的 PostgreSQL 镜像。静态字段 + 静态初始化 = 单例容器，
     * 跨测试类共享；JVM 退出后由 Ryuk reaper 负责清理。
     */
    static final PostgreSQLContainer<?> POSTGRES = new PostgreSQLContainer<>(
            DockerImageName.parse("postgres:15.17-alpine"))
            .withDatabaseName("kinlin_ai")
            .withUsername("kinlin_it")
            .withPassword("kinlin_it_password");

    static {
        try {
            POSTGRES.start();
        } catch (Throwable failure) {
            throw new IllegalStateException(
                    "BLOCKED_BY_DOCKER: PostgreSQL 持久化契约测试需要 Docker（Testcontainers）。"
                            + "请启动 Docker Desktop 后重跑 mvn test。本失败是显式失败，不是静默 skip。原因: "
                            + failure.getMessage(),
                    failure);
        }
    }

    /**
     * 动态注入容器连接信息（覆盖 canonical 的 localhost 默认值），
     * 因此测试不依赖固定端口、本机 PostgreSQL 或本地密码，可直接进 CI。
     */
    @DynamicPropertySource
    static void containerDatasource(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        registry.add("spring.datasource.username", POSTGRES::getUsername);
        registry.add("spring.datasource.password", POSTGRES::getPassword);
    }
}
