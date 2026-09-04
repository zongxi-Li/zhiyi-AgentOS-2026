package com.kinlin.ai.controller;

import com.kinlin.ai.service.ChatQualityService;
import com.kinlin.ai.service.ChatService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

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
     * 评估对话质量
     */
    @GetMapping("/{contextId}")
    public ResponseEntity<Map<String, Object>> assessQuality(@PathVariable String contextId) {
        var messages = chatService.getHistory(contextId);
        var score = qualityService.assessQuality(messages);

        return ResponseEntity.ok(Map.of(
                "score", score.score(),
                "feedback", score.feedback(),
                "messageCount", messages.size()
        ));
    }
}

