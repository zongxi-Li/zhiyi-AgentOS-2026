package com.kinlin.ai.integration;

import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

/**
 * J1.4B Redis 缓存契约测试基座：复用共享 PostgreSQL 临时集群，另起一个
 * 测试 JVM 自管的真实 Redis（Windows 用 N03 同源 Memurai，Linux/CI 用
 * redis-server）——不再依赖 Docker/Testcontainers 容器。
 *
 * <p>profile 只声明 redis-it（自足 profile，见 application-redis-it.yml）——
 * 继承 {@link PostgresContainerBase} 的实例但不继承 pg-it profile，
 * 避免 @ActiveProfiles 层次合并把 pg-it 的 Redis 自动配置排除带进来。</p>
 *
 * <p>Redis 二进制缺失或启动失败时显式 BLOCKED_BY_REDIS 失败（与 J1.4A 同策略，
 * 不静默 skip）。降级测试通过 {@link #stopRedis()} / {@link #restartRedis()}
 * 操作本基座自己 spawn 的进程（复用同一端口，应用上下文无需重建）。</p>
 */
@ActiveProfiles("redis-it")
public abstract class RedisIntegrationTestBase extends PostgresContainerBase {

    public static final NativeRedis REDIS;

    static {
        try {
            REDIS = NativeRedis.start();
        } catch (Throwable failure) {
            throw new IllegalStateException(
                    "BLOCKED_BY_REDIS: Redis 缓存契约测试需要本机 Memurai/redis-server 真实例"
                            + "（已不再使用 Docker/Testcontainers）。请设置 ZHIYI_REDIS_BIN，"
                            + "或准备 N03 同源 Memurai 依赖包 / 在 CI 安装 redis-server。"
                            + "本失败是显式失败，不是静默 skip。原因: " + failure.getMessage(),
                    failure);
        }
    }

    @DynamicPropertySource
    static void testInstanceRedis(DynamicPropertyRegistry registry) {
        registry.add("spring.data.redis.host", REDIS::getHost);
        registry.add("spring.data.redis.port", REDIS::getPort);
    }

    /** 停掉本基座自己 spawn 的 Redis（降级测试用）。 */
    protected static void stopRedis() {
        REDIS.stop();
    }

    /** 复用同一端口重启本基座自己 spawn 的 Redis。 */
    protected static void restartRedis() {
        REDIS.restart();
    }
}
