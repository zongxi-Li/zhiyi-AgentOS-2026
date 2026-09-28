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
            @Valid @RequestBody ChatRequest request
    ) {
        ChatResponse response = chatService.sendMessage(request, resolveUserId());
        return ResponseEntity.ok(response);
    }

    /**
     * 获取对话历史（仅属主可见）
     */
    @GetMapping("/history/{contextId}")
    public ResponseEntity<List<Message>> getHistory(
            @PathVariable String contextId
    ) {
        List<Message> history = chatService.getHistory(contextId, requireUserId());
        return ResponseEntity.ok(history);
    }

    /**
     * 清除对话历史（仅属主可操作）
     */
    @DeleteMapping("/history/{contextId}")
    public ResponseEntity<Void> clearHistory(
            @PathVariable String contextId
    ) {
        chatService.clearHistory(contextId, requireUserId());
        return ResponseEntity.ok().build();
    }

    /**
     * X-User-Id 请求头已被 SensitiveIdentityHeaderFilter 剥离，一律以认证身份为准。
     */
    private UUID resolveUserId() {
        return AuthenticatedUser.currentUserId().orElse(null);
    }

    private UUID requireUserId() {
        return AuthenticatedUser.currentUserId()
                .orElseThrow(() -> new ResourceNotFoundException("会话不存在或无权访问"));
    }
}
