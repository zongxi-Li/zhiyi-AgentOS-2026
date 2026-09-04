package com.kinlin.ai.controller;

import com.kinlin.ai.dto.ChatRequest;
import com.kinlin.ai.dto.ChatResponse;
import com.kinlin.ai.service.ChatService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.messaging.handler.annotation.MessageMapping;
import org.springframework.messaging.handler.annotation.Payload;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.stereotype.Controller;

import java.util.UUID;

/**
 * WebSocket控制器
 * 处理实时消息通信
 */
@Slf4j
@Controller
@RequiredArgsConstructor
public class WebSocketController {

    private final ChatService chatService;
    private final SimpMessagingTemplate messagingTemplate;

    /**
     * 处理WebSocket消息
     */
    @MessageMapping("/chat/message")
    public void handleMessage(@Payload ChatRequest request) {
        log.info("收到WebSocket消息: {}", request.getText());
        
        try {
            // 处理消息（这里需要从WebSocket session获取userId）
            ChatResponse response = chatService.sendMessage(request, null);
            
            // 发送回复给客户端
            messagingTemplate.convertAndSend("/topic/chat/" + response.getContextId(), response);
        } catch (Exception e) {
            log.error("处理WebSocket消息失败", e);
            messagingTemplate.convertAndSend("/topic/errors", 
                "处理消息失败: " + e.getMessage());
        }
    }
}

