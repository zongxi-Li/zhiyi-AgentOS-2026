package com.kinlin.ai.security;

import java.util.UUID;

/**
 * Immutable identity created only after successful JWT verification.
 *
 * <p>INT-2F-4A 起，过滤器产生的完整上下文携带登录会话 {@code sid}；
 * 会话敏感操作（如服务端登出）必须校验 {@code sid != null}，
 * 不得让无 sid 的兼容分支（UUID/String principal）通过。</p>
 */
public record AuthenticatedUserContext(
        UUID userId,
        String subject,
        String role,
        UUID sid,
        String tenantId,
        String traceId
) {
    /** 兼容构造：无会话标识的上下文（兼容 principal 分支与既有调用）。 */
    public AuthenticatedUserContext(UUID userId, String subject, String role, String tenantId, String traceId) {
        this(userId, subject, role, null, tenantId, traceId);
    }
}
