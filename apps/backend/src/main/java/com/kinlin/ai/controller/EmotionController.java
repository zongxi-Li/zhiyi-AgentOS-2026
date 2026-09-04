package com.kinlin.ai.controller;

import com.kinlin.ai.dto.EmotionAnalyzeRequest;
import com.kinlin.ai.dto.EmotionAwareResponseRequest;
import com.kinlin.ai.service.EmotionAwareService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

/**
 * 情感感知控制器
 */
@Slf4j
@RestController
@RequestMapping("/api/emotion")
@RequiredArgsConstructor
public class EmotionController {

    private final EmotionAwareService emotionAwareService;

    /**
     * 多模态情感分析
     */
    @PostMapping("/analyze")
    public ResponseEntity<Map<String, Object>> analyzeEmotion(
            @Valid @RequestBody EmotionAnalyzeRequest request
    ) {
        Map<String, Object> result = emotionAwareService.analyzeEmotion(request);
        return ResponseEntity.ok(result);
    }

    /**
     * 生成情感感知回复
     */
    @PostMapping("/response")
    public ResponseEntity<Map<String, Object>> generateEmotionAwareResponse(
            @Valid @RequestBody EmotionAwareResponseRequest request
    ) {
        Map<String, Object> result = emotionAwareService.generateEmotionAwareResponse(request);
        return ResponseEntity.ok(result);
    }
}

