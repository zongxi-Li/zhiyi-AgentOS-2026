package com.kinlin.ai.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.Data;

import java.time.LocalDateTime;
import java.util.UUID;

/**
 * IAM 登录会话（INT-2F-4A）。
 *
 * <p>每次登录/注册创建一行，sid 写入签发的 JWT；服务端撤销 = 写入 revoked_at。
 * revoked_at 为 null 且未过 expires_at 才可用于认证；EXPIRED 由到期派生，
 * 不落第二份状态。sid 由服务端安全随机生成，不是持有即可登录的秘密。</p>
 */
@Entity
@Table(name = "iam_login_sessions")
@Data
public class LoginSession {

    @Id
    private UUID sid;

    @Column(name = "user_id", nullable = false)
    private UUID userId;

    @Column(name = "created_at", nullable = false, updatable = false)
    private LocalDateTime createdAt;

    @Column(name = "expires_at", nullable = false)
    private LocalDateTime expiresAt;

    /** null = 尚未主动撤销；一旦写入不再清空。 */
    @Column(name = "revoked_at")
    private LocalDateTime revokedAt;
}
