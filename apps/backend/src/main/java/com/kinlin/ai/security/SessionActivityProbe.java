package com.kinlin.ai.security;

import java.util.UUID;

/**
 * 登录会话有效性探针（INT-2F-4B）。
 *
 * <p>SSE 流的周期会话复核与 HTTP 认证共用同一持久会话权威的窄接口。
 * 放在 security 领域包以维持 J1.2 依赖方向：transport（gateway）依赖本
 * 接口，由 IAM 服务层实现；查询失败以异常上抛，调用方 fail-closed。</p>
 */
@FunctionalInterface
public interface SessionActivityProbe {

    /** 会话是否存在、归属匹配、未撤销且未到期；无法确认时抛 DataAccessException。 */
    boolean isSessionActive(UUID sid, UUID userId);
}
