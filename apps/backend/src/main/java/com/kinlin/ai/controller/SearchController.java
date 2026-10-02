package com.kinlin.ai.controller;

import com.kinlin.ai.entity.Message;
import com.kinlin.ai.projection.message.dto.MessageQuery;
import com.kinlin.ai.projection.message.mapper.MessageProjectionMapper;
import com.kinlin.ai.security.AuthenticatedUser;
import com.kinlin.ai.service.ChatService;
import com.kinlin.ai.service.SearchService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.UUID;

/**
 * 搜索控制器
 */
@RestController
@RequestMapping("/search")
@RequiredArgsConstructor
public class SearchController {

    private final ChatService chatService;
    private final SearchService searchService;

    /**
     * 搜索对话消息
     */
    @GetMapping("/messages")
    public ResponseEntity<List<MessageQuery>> searchMessages(
            @RequestParam("keyword") String keyword,
            @RequestParam(value = "contextId", required = false) String contextId
    ) {
        UUID userId = resolveUserId();
        if (userId == null) {
            return ResponseEntity.badRequest().build();
        }
        if (contextId != null && !contextId.isEmpty()) {
            List<Message> messages = chatService.getHistory(contextId, userId);
            List<Message> results = messages.stream()
                    .filter(msg -> msg.getContent().toLowerCase().contains(keyword.toLowerCase()))
                    .toList();
            return ResponseEntity.ok(MessageProjectionMapper.toQuery(results));
        }
        return ResponseEntity.ok(List.of());
    }

    /**
     * 搜索用户的所有消息
     */
    @GetMapping("/all-messages")
    public ResponseEntity<List<MessageQuery>> searchAllMessages(
            @RequestParam("keyword") String keyword
    ) {
        UUID userId = resolveUserId();
        if (userId == null) {
            return ResponseEntity.badRequest().build();
        }

        // 跨对话搜索当前用户会话中包含关键词的消息（最多200条）
        List<Message> results = searchService.searchMessages(userId, keyword);

        return ResponseEntity.ok(MessageProjectionMapper.toQuery(results));
    }

    /**
     * X-User-Id 请求头已被 SensitiveIdentityHeaderFilter 剥离，一律以认证身份为准。
     */
    private UUID resolveUserId() {
        return AuthenticatedUser.currentUserId().orElse(null);
    }
}

