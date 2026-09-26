package com.kinlin.ai.controller;

import com.kinlin.ai.dto.ChatRequest;
import com.kinlin.ai.dto.ChatResponse;
import com.kinlin.ai.entity.Message;
import com.kinlin.ai.exception.ResourceNotFoundException;
import com.kinlin.ai.security.AuthenticatedUser;
import com.kinlin.ai.service.ChatService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.UUID;

/**
 * 对话控制器
 */
@RestController
@RequestMapping("/chat")
@RequiredArgsConstructor
public class ChatController {

    private final ChatService chatService;

    /**
     * 发送文本消息
     */
    @PostMapping("/text")
    public ResponseEntity<ChatResponse> sendTextMessage(
            @Valid @RequestBody ChatRequest request,
            @RequestHeader(value = "X-User-Id", required = false) UUID userId
    ) {
        ChatResponse response = chatService.sendMessage(request, resolveUserId(userId));
        return ResponseEntity.ok(response);
    }

    /**
     * 获取对话历史（仅属主可见）
     */
    @GetMapping("/history/{contextId}")
    public ResponseEntity<List<Message>> getHistory(
            @PathVariable String contextId,
            @RequestHeader(value = "X-User-Id", required = false) UUID userId
    ) {
        List<Message> history = chatService.getHistory(contextId, requireUserId(userId));
        return ResponseEntity.ok(history);
    }

    /**
     * 清除对话历史（仅属主可操作）
     */
    @DeleteMapping("/history/{contextId}")
    public ResponseEntity<Void> clearHistory(
            @PathVariable String contextId,
            @RequestHeader(value = "X-User-Id", required = false) UUID userId
    ) {
        chatService.clearHistory(contextId, requireUserId(userId));
        return ResponseEntity.ok().build();
    }

    private UUID resolveUserId(UUID userIdHeader) {
        return AuthenticatedUser.currentUserId().orElse(userIdHeader);
    }

    private UUID requireUserId(UUID userIdHeader) {
        return AuthenticatedUser.currentUserId()
                .orElseThrow(() -> new ResourceNotFoundException("会话不存在或无权访问"));
    }
}

