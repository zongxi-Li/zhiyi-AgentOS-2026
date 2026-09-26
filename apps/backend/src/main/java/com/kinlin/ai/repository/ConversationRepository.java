package com.kinlin.ai.repository;

import com.kinlin.ai.entity.Conversation;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.lang.NonNull;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

/**
 * 对话数据访问接口
 */
@Repository
public interface ConversationRepository extends JpaRepository<Conversation, UUID> {

    Optional<Conversation> findByContextId(String contextId);

    Optional<Conversation> findByUserIdAndRoleId(UUID userId, UUID roleId);

    List<Conversation> findByUserId(UUID userId);

    @Query("SELECT c FROM Conversation c WHERE c.userId = :userId ORDER BY c.updatedAt DESC")
    List<Conversation> findRecentConversationsByUserId(@Param("userId") UUID userId);

    @Query("SELECT c FROM Conversation c WHERE c.userId = :userId AND c.workspaceMode = :workspaceMode ORDER BY c.updatedAt DESC")
    List<Conversation> findRecentConversationsByUserIdAndWorkspaceMode(
            @Param("userId") UUID userId,
            @Param("workspaceMode") String workspaceMode
    );

    @Query("select distinct c.userId from Conversation c where c.createdAt > :since and c.userId is not null")
    List<UUID> findActiveUserIdsSince(@NonNull @Param("since") LocalDateTime since);
}

