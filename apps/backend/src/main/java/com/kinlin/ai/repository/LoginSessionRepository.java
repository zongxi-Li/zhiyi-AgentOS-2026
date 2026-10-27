package com.kinlin.ai.repository;

import com.kinlin.ai.entity.LoginSession;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.LocalDateTime;
import java.util.UUID;

/**
 * IAM 登录会话持久权威（INT-2F-4A）。
 */
public interface LoginSessionRepository extends JpaRepository<LoginSession, UUID> {

    /**
     * 条件撤销：仅首次写入 revoked_at，重复撤销不覆写原撤销时间（幂等）。
     *
     * @return 1 = 本次完成撤销；0 = 会话不存在或此前已撤销
     */
    @Modifying
    @Query("update LoginSession s set s.revokedAt = :now where s.sid = :sid and s.revokedAt is null")
    int revokeBySid(@Param("sid") UUID sid, @Param("now") LocalDateTime now);
}
