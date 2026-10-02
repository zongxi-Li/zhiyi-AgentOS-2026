package com.kinlin.ai.controller;

import com.kinlin.ai.entity.Conversation;
import com.kinlin.ai.exception.ResourceNotFoundException;
import com.kinlin.ai.projection.conversation.dto.ConversationDetailQuery;
import com.kinlin.ai.projection.conversation.dto.ConversationQuery;
import com.kinlin.ai.projection.conversation.mapper.ConversationProjectionMapper;
import com.kinlin.ai.security.AuthenticatedUser;
import com.kinlin.ai.service.ConversationService;
import lombok.Data;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;
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
    public ResponseEntity<List<ConversationQuery>> getUserConversations(
            @RequestParam(value = "workspaceMode", required = false) String workspaceMode
    ) {
        UUID userId = resolveUserId();
        if (userId == null) {
            return ResponseEntity.badRequest().build();
        }
        List<Conversation> conversations = workspaceMode == null
                ? conversationService.getUserConversations(userId)
                : conversationService.getUserConversations(userId, workspaceMode);
        return ResponseEntity.ok(conversations.stream()
                .map(ConversationProjectionMapper::toQuery)
                .toList());
    }

    /**
     * 获取对话详情（仅属主可见）
     */
    @GetMapping("/{contextId}")
    public ResponseEntity<ConversationQuery> getConversation(
            @PathVariable String contextId
    ) {
        Conversation conversation = conversationService
                .getConversationByContextIdForUser(contextId, requireUserId())
                .orElseThrow(() -> new ResourceNotFoundException("会话不存在或无权访问"));
        return ResponseEntity.ok(ConversationProjectionMapper.toQuery(conversation));
    }

    /**
     * 删除对话
     */
    @DeleteMapping("/{conversationId}")
    public ResponseEntity<Void> deleteConversation(
            @PathVariable UUID conversationId
    ) {
        UUID userId = resolveUserId();
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
    public ResponseEntity<ConversationQuery> updateTitle(
            @PathVariable UUID conversationId,
            @RequestBody UpdateTitleRequest request
    ) {
        Conversation conversation = conversationService
                .updateTitle(conversationId, requireUserId(), request.getTitle());
        return ResponseEntity.ok(ConversationProjectionMapper.toQuery(conversation));
    }

    /**
     * 获取对话详情（包含预览内容，仅属主可见）
     */
    @GetMapping("/{conversationId}/detail")
    public ResponseEntity<ConversationDetailQuery> getConversationDetail(
            @PathVariable UUID conversationId
    ) {
        Conversation conversation = conversationService
                .getConversationByIdForUser(conversationId, requireUserId())
                .orElseThrow(() -> new ResourceNotFoundException("会话不存在或无权访问"));

        // 自动生成标题（如果还没有）
        if (conversation.getTitle() == null || conversation.getTitle().isEmpty()) {
            conversation = conversationService.autoGenerateTitle(conversationId);
        }

        String preview = conversationService.getPreviewContent(conversationId);

        return ResponseEntity.ok(ConversationProjectionMapper.toDetail(conversation, preview));
    }

    /**
     * 清空用户的所有对话
     */
    @DeleteMapping("/all")
    public ResponseEntity<Void> deleteAllConversations(
            @RequestParam(value = "workspaceMode", required = false) String workspaceMode
    ) {
        UUID userId = resolveUserId();
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

    @Data
    static class UpdateTitleRequest {
        private String title;
    }
}

