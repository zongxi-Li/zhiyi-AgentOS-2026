package com.kinlin.ai.config;

import org.junit.jupiter.api.Test;
import org.springframework.boot.autoconfigure.AutoConfigurations;
import org.springframework.boot.autoconfigure.context.ConfigurationPropertiesAutoConfiguration;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * JwtProperties fail-closed 校验测试（J1.4B §八/§九）。
 */
class JwtPropertiesTest {

    private static final String SECRET_64_BYTES =
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

    private static void validate(JwtProperties properties) {
        // 与 @PostConstruct 相同入口
        properties.validateConfiguration();
    }

    @Test
    void validConfigurationPasses() {
        JwtProperties properties = new JwtProperties();
        properties.setSecret(SECRET_64_BYTES);
        properties.setExpiration(86_400_000L);

        assertThatCode(() -> validate(properties)).doesNotThrowAnyException();
    }

    @Test
    void blankSecretFailsStartup() {
        JwtProperties properties = new JwtProperties();
        properties.setSecret("   ");
        properties.setExpiration(86_400_000L);

        assertThatThrownBy(properties::validateConfiguration)
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("missing or blank");
    }

    @Test
    void shortSecretFailsStartup() {
        JwtProperties properties = new JwtProperties();
        // 63 字节：恰好低于 HS512 最低 64 字节
        properties.setSecret("x".repeat(63));
        properties.setExpiration(86_400_000L);

        assertThatThrownBy(properties::validateConfiguration)
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("64");
    }

    @Test
    void nonPositiveExpirationFailsStartup() {
        JwtProperties properties = new JwtProperties();
        properties.setSecret(SECRET_64_BYTES);
        properties.setExpiration(0L);

        assertThatThrownBy(properties::validateConfiguration)
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("positive");
    }

    /**
     * 生产 fail-closed 机制证明：prod/compose yml 声明
     * {@code app.jwt.secret: ${APP_JWT_SECRET}}（无默认值），环境变量缺失时
     * 占位符无法解析 → 上下文启动失败，绝不会静默绑定仓库默认 secret。
     */
    @Test
    void unresolvedRequiredSecretFailsApplicationContext() {
        new ApplicationContextRunner()
                .withConfiguration(AutoConfigurations.of(ConfigurationPropertiesAutoConfiguration.class))
                .withUserConfiguration(JwtProperties.class)
                .withPropertyValues("app.jwt.secret=${APP_JWT_SECRET}")
                .run(context -> assertThat(context).hasFailed());
    }

    @Test
    void providedSecretStartsApplicationContext() {
        new ApplicationContextRunner()
                .withConfiguration(AutoConfigurations.of(ConfigurationPropertiesAutoConfiguration.class))
                .withUserConfiguration(JwtProperties.class)
                .withPropertyValues(
                        "app.jwt.secret=" + SECRET_64_BYTES,
                        "app.jwt.expiration=86400000")
                .run(context -> {
                    assertThat(context).hasNotFailed();
                    assertThat(context.getBean(JwtProperties.class).getSecret())
                            .isEqualTo(SECRET_64_BYTES);
                });
    }
}
