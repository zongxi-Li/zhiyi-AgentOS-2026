package com.kinlin.ai.integration;

import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.utility.DockerImageName;

/**
 * J1.4B Redis 缓存契约测试基座：复用共享 PostgreSQL 单例容器，另起真实 Redis
 * 容器（版本对齐生产 redis:7.4.9-alpine，见 ops/docker/base-images.json
 * redisRuntime）。
 *
 * <p>profile 只声明 redis-it（自足 profile，见 application-redis-it.yml）——
 * 继承 {@link PostgresContainerBase} 的容器但不继承 pg-it profile，
 * 避免 @ActiveProfiles 层次合并把 pg-it 的 Redis 自动配置排除带进来。</p>
 *
 * <p>Docker 不可用时显式 BLOCKED_BY_DOCKER 失败（与 J1.4A 同策略，不静默 skip）。</p>
 */
@ActiveProfiles("redis-it")
public abstract class RedisIntegrationTestBase extends PostgresContainerBase {

    static final GenericContainer<?> REDIS = new GenericContainer<>(
            DockerImageName.parse("redis:7.4.9-alpine"))
            .withExposedPorts(6379);

    static {
        try {
            REDIS.start();
        } catch (Throwable failure) {
            throw new IllegalStateException(
                    "BLOCKED_BY_DOCKER: Redis 缓存契约测试需要 Docker（Testcontainers）。"
                            + "请启动 Docker Desktop 后重跑 mvn test。本失败是显式失败，不是静默 skip。原因: "
                            + failure.getMessage(),
                    failure);
        }
    }

    @DynamicPropertySource
    static void containerRedis(DynamicPropertyRegistry registry) {
        registry.add("spring.data.redis.host", REDIS::getHost);
        registry.add("spring.data.redis.port", () -> REDIS.getMappedPort(6379));
    }
}
