package com.kinlin.ai.controller;

import com.kinlin.ai.entity.Conversation;
import com.kinlin.ai.exception.ResourceNotFoundException;
import com.kinlin.ai.security.AuthenticatedUser;
import com.kinlin.ai.service.ConversationService;
import lombok.Data;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * 对话会话控制器
 */
@RestController
@RequestMapping("/conversations")
@RequiredArgsConstructor
public class ConversationController {

    private final ConversationService conversationService;

    /**
     * 获取用户的对话列表
     */
    @GetMapping
    public ResponseEntity<List<Conversation>> getUserConversations(
            @RequestHeader(value = "X-User-Id", required = false) UUID userId,
            @RequestParam(value = "workspaceMode", required = false) String workspaceMode
    ) {
        userId = resolveUserId(userId);
        if (userId == null) {
            return ResponseEntity.badRequest().build();
        }
        List<Conversation> conversations = workspaceMode == null
                ? conversationService.getUserConversations(userId)
                : conversationService.getUserConversations(userId, workspaceMode);
        return ResponseEntity.ok(conversations);
    }

    /**
     * 获取对话详情（仅属主可见）
     */
    @GetMapping("/{contextId}")
    public ResponseEntity<Conversation> getConversation(
            @PathVariable String contextId,
            @RequestHeader(value = "X-User-Id", required = false) UUID userId
    ) {
        Conversation conversation = conversationService
                .getConversationByContextIdForUser(contextId, requireUserId(userId))
                .orElseThrow(() -> new ResourceNotFoundException("会话不存在或无权访问"));
        return ResponseEntity.ok(conversation);
    }

    /**
     * 删除对话
     */
    @DeleteMapping("/{conversationId}")
    public ResponseEntity<Void> deleteConversation(
            @PathVariable UUID conversationId,
            @RequestHeader(value = "X-User-Id", required = false) UUID userId
    ) {
        userId = resolveUserId(userId);
        if (userId == null) {
            return ResponseEntity.badRequest().build();
        }
        return conversationService.deleteConversation(conversationId, userId)
                ? ResponseEntity.noContent().build()
                : ResponseEntity.notFound().build();
    }

    /**
     * 更新对话标题（仅属主可操作）
     */
    @PutMapping("/{conversationId}/title")
    public ResponseEntity<Conversation> updateTitle(
            @PathVariable UUID conversationId,
            @RequestBody UpdateTitleRequest request,
            @RequestHeader(value = "X-User-Id", required = false) UUID userId
    ) {
        Conversation conversation = conversationService
                .updateTitle(conversationId, requireUserId(userId), request.getTitle());
        return ResponseEntity.ok(conversation);
    }

    /**
     * 获取对话详情（包含预览内容，仅属主可见）
     */
    @GetMapping("/{conversationId}/detail")
    public ResponseEntity<Map<String, Object>> getConversationDetail(
            @PathVariable UUID conversationId,
            @RequestHeader(value = "X-User-Id", required = false) UUID userId
    ) {
        Conversation conversation = conversationService
                .getConversationByIdForUser(conversationId, requireUserId(userId))
                .orElseThrow(() -> new ResourceNotFoundException("会话不存在或无权访问"));

        // 自动生成标题（如果还没有）
        if (conversation.getTitle() == null || conversation.getTitle().isEmpty()) {
            conversation = conversationService.autoGenerateTitle(conversationId);
        }
        
        String preview = conversationService.getPreviewContent(conversationId);
        
        Map<String, Object> result = new HashMap<>();
        result.put("conversation", conversation);
        result.put("preview", preview);
        
        return ResponseEntity.ok(result);
    }

    /**
     * 清空用户的所有对话
     */
    @DeleteMapping("/all")
    public ResponseEntity<Void> deleteAllConversations(
            @RequestHeader(value = "X-User-Id", required = false) UUID userId,
            @RequestParam(value = "workspaceMode", required = false) String workspaceMode
    ) {
        userId = resolveUserId(userId);
        if (userId == null) {
            return ResponseEntity.badRequest().build();
        }
        if (workspaceMode == null) {
            conversationService.deleteAllConversations(userId);
        } else {
            conversationService.deleteAllConversations(userId, workspaceMode);
        }
        return ResponseEntity.ok().build();
    }

    private UUID resolveUserId(UUID userIdHeader) {
        return AuthenticatedUser.currentUserId().orElse(userIdHeader);
    }

    private UUID requireUserId(UUID userIdHeader) {
        return AuthenticatedUser.currentUserId()
                .orElseThrow(() -> new ResourceNotFoundException("会话不存在或无权访问"));
    }

    @Data
    static class UpdateTitleRequest {
        private String title;
    }
}

