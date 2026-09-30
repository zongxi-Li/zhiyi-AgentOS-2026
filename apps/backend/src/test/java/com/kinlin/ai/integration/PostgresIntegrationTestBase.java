package com.kinlin.ai.integration;

import org.springframework.test.context.ActiveProfiles;

/**
 * J1.4A 持久化契约测试基座：真实 PostgreSQL + pg-it profile。
 * profile 声明只在本层（见 {@link PostgresContainerBase} 的合并警告）。
 */
@ActiveProfiles("pg-it")
public abstract class PostgresIntegrationTestBase extends PostgresContainerBase {
}
