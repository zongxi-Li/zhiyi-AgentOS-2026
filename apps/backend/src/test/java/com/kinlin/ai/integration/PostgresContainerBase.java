package com.kinlin.ai.integration;

import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.utility.DockerImageName;

/**
 * 共享 PostgreSQL 单例容器基座（无 profile 声明）。
 *
 * <p>整个测试 JVM 共享一个真实 PostgreSQL 容器（singleton container 模式），
 * 版本对齐生产镜像（ops/docker/base-images.json: postgres:15.17-alpine）。
 * 各测试基座（pg-it / redis-it）继承本类后各自声明 profile——
 * 注意 @ActiveProfiles 沿类层次<b>合并</b>，因此本类绝不携带 profile 注解，
 * 否则兄弟 profile 的 yml（含 spring.autoconfigure.exclude）会串台。</p>
 *
 * <p>Docker 不可用时的行为：容器启动失败以 BLOCKED_BY_DOCKER 的
 * IllegalStateException 直接失败——显式失败，不是静默 skip（任务书 §十九）。</p>
 */
public abstract class PostgresContainerBase {

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

    /** 动态注入容器连接信息，测试不依赖固定端口/本机 PostgreSQL/本地密码，可直接进 CI。 */
    @DynamicPropertySource
    static void containerDatasource(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        registry.add("spring.datasource.username", POSTGRES::getUsername);
        registry.add("spring.datasource.password", POSTGRES::getPassword);
    }
}
