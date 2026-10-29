package com.kinlin.ai.config;

import jakarta.annotation.PostConstruct;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;

/**
 * JWT 配置（typed owner，J1.4B 收敛）。
 *
 * <p>此前 secret/expiration 散在 JwtUtil 的 @Value 中且零校验。收敛后：</p>
 * <ul>
 *   <li>secret 非空且 ≥ 64 字节（HS512 要求 512 位密钥，不足时 jjwt 会在
 *       签名期抛 WeakKeyException，fail-fast 到启动期而非首个请求）。</li>
 *   <li>expiration &gt; 0。</li>
 *   <li>生产 fail-closed：application-prod 声明
 *       {@code app.jwt.secret: ${APP_JWT_SECRET}}（无仓库默认值）——
 *       原生运行形态（N03 persistent_runtime）在进程环境注入；缺失时
 *       占位符解析失败使应用启动失败，禁止回落仓库默认 secret。</li>
 * </ul>
 *
 * <p>dev/test 继承 canonical 的稳定开发默认 secret，属允许的非生产测试值。</p>
 */
@Component
@ConfigurationProperties(prefix = "app.jwt")
public class JwtProperties {

    /** HS512 所需最低密钥字节数（512 bits）。 */
    public static final int HS512_MINIMUM_SECRET_BYTES = 64;

    private String secret = "";
    private Long expiration = 0L;

    @PostConstruct
    void validateConfiguration() {
        if (secret == null || secret.isBlank()) {
            throw new IllegalStateException("app.jwt.secret is missing or blank");
        }
        if (secret.getBytes(StandardCharsets.UTF_8).length < HS512_MINIMUM_SECRET_BYTES) {
            throw new IllegalStateException("app.jwt.secret is shorter than the "
                    + HS512_MINIMUM_SECRET_BYTES + " bytes required for HS512");
        }
        if (expiration == null || expiration <= 0) {
            throw new IllegalStateException("app.jwt.expiration must be positive");
        }
    }

    public String getSecret() {
        return secret;
    }

    public void setSecret(String secret) {
        this.secret = secret;
    }

    public Long getExpiration() {
        return expiration;
    }

    public void setExpiration(Long expiration) {
        this.expiration = expiration;
    }
}
