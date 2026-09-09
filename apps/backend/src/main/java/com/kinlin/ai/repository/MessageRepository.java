package com.kinlin.ai.repository;

import com.kinlin.ai.entity.Message;
import org.springframework.data.jpa.repository.JpaRepository;
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
}

