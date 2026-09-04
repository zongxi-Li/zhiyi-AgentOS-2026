package com.kinlin.ai.service;

import lombok.extern.slf4j.Slf4j;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.stereotype.Service;

import java.util.Map;
import java.util.UUID;

/**
 * 通知服务
 * 用于发送实时通知
 */
@Slf4j
@Service
public class NotificationService {

    private final SimpMessagingTemplate messagingTemplate;

    public NotificationService(SimpMessagingTemplate messagingTemplate) {
        this.messagingTemplate = messagingTemplate;
    }

    /**
     * 发送通知给用户
     */
    public void sendNotification(UUID userId, String message) {
        messagingTemplate.convertAndSend(
                "/topic/notifications/" + userId,
                Map.of("message", message, "timestamp", System.currentTimeMillis())
        );
    }

    /**
     * 发送系统通知
     */
    public void sendSystemNotification(String message) {
        messagingTemplate.convertAndSend(
                "/topic/notifications/system",
                Map.of("message", message, "timestamp", System.currentTimeMillis())
        );
    }
}

