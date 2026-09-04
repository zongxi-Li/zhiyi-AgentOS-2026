package com.kinlin.ai.entity;

import jakarta.persistence.*;
import lombok.Data;
import org.springframework.data.annotation.CreatedDate;
import org.springframework.data.jpa.domain.support.AuditingEntityListener;

import java.time.LocalDateTime;
import java.util.UUID;

/**
 * 用户反馈实体类
 */
@Entity
@Table(name = "user_feedback")
@Data
@EntityListeners(AuditingEntityListener.class)
public class UserFeedback {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;

    @Column(name = "user_id", nullable = false)
    private UUID userId;

    @Column(name = "conversation_id")
    private UUID conversationId;

    @Column(name = "message_id")
    private UUID messageId;

    @Column(name = "role_id")
    private UUID roleId;

    /**
     * 反馈类型：quality（质量）、relevance（相关性）、helpfulness（有用性）、other（其他）
     */
    @Column(name = "feedback_type", nullable = false, length = 50)
    private String feedbackType;

    /**
     * 反馈评分：1-5分
     */
    @Column(name = "rating")
    private Integer rating;

    /**
     * 反馈内容
     */
    @Column(name = "content", columnDefinition = "TEXT")
    private String content;

    /**
     * 反馈标签：positive（正面）、negative（负面）、neutral（中性）
     */
    @Column(name = "sentiment", length = 20)
    private String sentiment;

    @CreatedDate
    @Column(name = "created_at", nullable = false, updatable = false)
    private LocalDateTime createdAt;
}

