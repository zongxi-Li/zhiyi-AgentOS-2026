package com.kinlin.ai.repository;

import com.kinlin.ai.entity.UserFeedback;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.UUID;

/**
 * 用户反馈数据访问接口
 */
@Repository
public interface UserFeedbackRepository extends JpaRepository<UserFeedback, UUID> {

    /**
     * 根据用户ID查找反馈
     */
    List<UserFeedback> findByUserId(UUID userId);

    /**
     * 根据对话ID查找反馈
     */
    List<UserFeedback> findByConversationId(UUID conversationId);

    /**
     * 根据消息ID查找反馈
     */
    List<UserFeedback> findByMessageId(UUID messageId);

    /**
     * 根据角色ID查找反馈
     */
    List<UserFeedback> findByRoleId(UUID roleId);

    /**
     * 根据反馈类型查找
     */
    List<UserFeedback> findByFeedbackType(String feedbackType);

    /**
     * 根据情感标签查找
     */
    List<UserFeedback> findBySentiment(String sentiment);

    /**
     * 统计用户反馈数量
     */
    @Query("SELECT COUNT(f) FROM UserFeedback f WHERE f.userId = :userId")
    long countByUserId(@Param("userId") UUID userId);

    /**
     * 计算平均评分
     */
    @Query("SELECT AVG(f.rating) FROM UserFeedback f WHERE f.userId = :userId AND f.rating IS NOT NULL")
    Double getAverageRatingByUserId(@Param("userId") UUID userId);

    /**
     * 统计各类型反馈数量
     */
    @Query("SELECT f.feedbackType, COUNT(f) FROM UserFeedback f GROUP BY f.feedbackType")
    List<Object[]> countByFeedbackType();
}

