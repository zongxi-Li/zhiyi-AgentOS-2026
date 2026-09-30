package com.kinlin.ai.repository;

import com.kinlin.ai.entity.Message;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.UUID;

/**
 * 消息数据访问接口
 */
@Repository
public interface MessageRepository extends JpaRepository<Message, UUID> {

    interface ConversationMessagePreview {
        UUID getConversationId();

        String getContent();
    }

    List<Message> findByConversationIdOrderByCreatedAtAsc(UUID conversationId);

    void deleteByConversationId(UUID conversationId);

    /**
     * J1.4C §十七 最小优化：bulk DELETE 替代"全量加载后逐实体删除"，
     * 语句数 O(1)（原形状为 select + N 条 DELETE 的 N+1）。绕过持久化上下文，
     * 调用方必须处于事务内且不再依赖受管 Message 实体。
     */
    @Modifying
    @Query("delete from Message m where m.conversationId = :conversationId")
    int deleteAllByConversationId(@Param("conversationId") UUID conversationId);

    /** 同上，多会话批量变体（deleteAllConversations）。 */
    @Modifying
    @Query("delete from Message m where m.conversationId in :conversationIds")
    int deleteAllByConversationIdIn(@Param("conversationIds") java.util.Collection<UUID> conversationIds);

    @Query("""
            SELECT m.conversationId AS conversationId, m.content AS content
            FROM Message m
            WHERE m.role = :role
              AND m.conversationId IN :conversationIds
              AND m.createdAt = (
                  SELECT MIN(firstMessage.createdAt)
                  FROM Message firstMessage
                  WHERE firstMessage.conversationId = m.conversationId
                    AND firstMessage.role = :role
              )
            """)
    List<ConversationMessagePreview> findFirstMessagePreviews(
            @Param("conversationIds") List<UUID> conversationIds,
            @Param("role") Message.MessageRole role
    );

    @Query("SELECT DISTINCT m.conversationId FROM Message m WHERE m.conversationId IN :conversationIds")
    List<UUID> findConversationIdsWithMessages(@Param("conversationIds") List<UUID> conversationIds);

    @Query("SELECT m FROM Message m WHERE m.conversationId = :conversationId ORDER BY m.createdAt DESC")
    List<Message> findRecentMessages(@Param("conversationId") UUID conversationId);

    List<Message> findByConversationIdIn(List<UUID> conversationIds);

    List<Message> findByConversationIdInAndContentContainingIgnoreCase(
            List<UUID> conversationIds, String content, Pageable pageable);
}

