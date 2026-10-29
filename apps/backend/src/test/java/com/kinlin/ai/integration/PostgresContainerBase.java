package com.kinlin.ai.integration;

import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

/**
 * 共享 PostgreSQL 测试基座（无 profile 声明）：测试 JVM 自管的真实临时集群。
 *
 * <p>整个测试 JVM 共享一个 {@link NativePostgres} 实例——由测试进程自己
 * {@code initdb} + 随机 loopback 端口启动，JVM 关闭时优雅停止并清理；
 * 不再依赖 Docker/Testcontainers。版本口径为 PostgreSQL 15.x 真实例
 * （本机二进制来自 N03 同源依赖包；CI 用发行版包）。</p>
 *
 * <p>各测试基座（pg-it / redis-it）继承本类后各自声明 profile——
 * 注意 @ActiveProfiles 沿类层次<b>合并</b>，因此本类绝不携带 profile 注解，
 * 否则兄弟 profile 的 yml（含 spring.autoconfigure.exclude）会串台。</p>
 *
 * <p>本机二进制缺失或启动失败时的行为：以 BLOCKED_BY_PG 的
 * IllegalStateException 直接失败——显式失败，不是静默 skip（任务书 §十九）。</p>
 */
public abstract class PostgresContainerBase {

    public static final NativePostgres POSTGRES;

    static {
        try {
            POSTGRES = NativePostgres.start("kinlin_ai", "kinlin_it", "kinlin_it_password");
        } catch (Throwable failure) {
            throw new IllegalStateException(
                    "BLOCKED_BY_PG: PostgreSQL 持久化契约测试需要本机 PostgreSQL 15.x 真实例"
                            + "（已不再使用 Docker/Testcontainers）。请设置 ZHIYI_PG_BIN 指向 PostgreSQL bin 目录，"
                            + "或运行 prepare_persistent_dependencies.py 准备 N03 同源依赖包 / 在 CI 安装 postgresql。"
                            + "本失败是显式失败，不是静默 skip。原因: " + failure.getMessage(),
                    failure);
        }
    }

    /** 动态注入自管临时实例连接信息，测试不依赖固定端口/本机既有数据库/本地密码，可直接进 CI。 */
    @DynamicPropertySource
    static void testClusterDatasource(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        registry.add("spring.datasource.username", POSTGRES::getUsername);
        registry.add("spring.datasource.password", POSTGRES::getPassword);
    }
}
