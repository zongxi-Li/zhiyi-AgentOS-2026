package com.kinlin.ai.service;

import com.kinlin.ai.config.JwtProperties;
import com.kinlin.ai.entity.LoginSession;
import com.kinlin.ai.entity.User;
import com.kinlin.ai.repository.LoginSessionRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.UUID;

/**
 * IAM 登录会话服务（INT-2F-4A）。
 *
 * <p>会话时长与 JWT exp 同源于 {@link JwtProperties#getExpiration()}，
 * 登录时同一时刻创建，保证两者到期一致。查询失败以 DataAccessException
 * 向上抛出，由调用方 fail-closed，不得默认有效。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class LoginSessionService {

    private final LoginSessionRepository loginSessionRepository;
    private final JwtProperties jwtProperties;

    /**
     * 登录/注册成功后创建持久会话。sid 由服务端随机生成；
     * 持久失败抛 DataAccessException，调用方不得签发 Token。
     */
    @Transactional
    public LoginSession createSession(User user) {
        LocalDateTime now = LocalDateTime.now();
        LoginSession session = new LoginSession();
        session.setSid(UUID.randomUUID());
        session.setUserId(user.getId());
        session.setCreatedAt(now);
        session.setExpiresAt(now.plusNanos(jwtProperties.getExpiration() * 1_000_000L));
        LoginSession saved = loginSessionRepository.save(session);
        log.info("登录会话已创建: user={}, sid={}", user.getId(), saved.getSid());
        return saved;
    }

    /**
     * 撤销当前登录会话。条件更新保证首次撤销事实不被覆写；重复撤销返回 false。
     */
    @Transactional
    public boolean revokeBySid(UUID sid) {
        boolean revoked = loginSessionRepository.revokeBySid(sid, LocalDateTime.now()) > 0;
        if (revoked) {
            log.info("登录会话已撤销: sid={}", sid);
        }
        return revoked;
    }

    /**
     * 会话是否仍可认证：存在、归属匹配、未撤销且未到期。
     * 数据库无法确认时抛 DataAccessException，绝不默认有效。
     */
    public boolean isSessionActive(UUID sid, UUID userId) {
        return loginSessionRepository.findById(sid)
                .filter(session -> userId.equals(session.getUserId()))
                .filter(session -> session.getRevokedAt() == null)
                .filter(session -> session.getExpiresAt().isAfter(LocalDateTime.now()))
                .isPresent();
    }
}
