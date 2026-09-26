package com.kinlin.ai.controller;

import com.kinlin.ai.exception.ResourceNotFoundException;
import com.kinlin.ai.security.AuthenticatedUser;
import com.kinlin.ai.service.ChatQualityService;
import com.kinlin.ai.service.ChatService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.Map;
import java.util.UUID;

/**
 * 对话质量评估控制器
 */
@RestController
@RequestMapping("/chat/quality")
@RequiredArgsConstructor
public class ChatQualityController {

    private final ChatQualityService qualityService;
    private final ChatService chatService;

    /**
     * 评估对话质量（仅属主可见）
     */
    @GetMapping("/{contextId}")
    public ResponseEntity<Map<String, Object>> assessQuality(
            @PathVariable String contextId,
            @RequestHeader(value = "X-User-Id", required = false) UUID userId
    ) {
        UUID currentUserId = AuthenticatedUser.currentUserId()
                .orElseThrow(() -> new ResourceNotFoundException("会话不存在或无权访问"));
        var messages = chatService.getHistory(contextId, currentUserId);
        var score = qualityService.assessQuality(messages);

        return ResponseEntity.ok(Map.of(
                "score", score.score(),
                "feedback", score.feedback(),
                "messageCount", messages.size()
        ));
    }
}

