package com.kinlin.ai.service;

import com.kinlin.ai.client.EmotionClient;
import com.kinlin.ai.client.PlatformAiClientException;
import com.kinlin.ai.dto.EmotionAnalyzeRequest;
import com.kinlin.ai.dto.EmotionAwareResponseRequest;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.HashMap;
import java.util.Map;

/**
 * 情感感知应用服务：情感能力的业务编排与 fallback 决策。
 *
 * <p>HTTP 细节与 {@code success/data} 信封解包已下沉到 {@link EmotionClient}；
 * transport 失败时保持既有用户可见行为（中性情感默认值 / error Map）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class EmotionAwareService {

    private final EmotionClient emotionClient;

    /**
     * 多模态情感分析
     */
    public Map<String, Object> analyzeEmotion(EmotionAnalyzeRequest request) {
        try {
            return emotionClient.analyzeEmotion(request);
        } catch (PlatformAiClientException e) {
            log.error("情感分析失败", e);
            Map<String, Object> defaultEmotion = new HashMap<>();
            defaultEmotion.put("emotion", "neutral");
            defaultEmotion.put("intensity", 0.5);
            return defaultEmotion;
        }
    }

    /**
     * 生成情感感知回复
     */
    public Map<String, Object> generateEmotionAwareResponse(EmotionAwareResponseRequest request) {
        try {
            return emotionClient.generateEmotionAwareResponse(request);
        } catch (PlatformAiClientException e) {
            log.error("生成情感感知回复失败", e);
            Map<String, Object> errorResponse = new HashMap<>();
            errorResponse.put("error", "生成情感感知回复失败: " + e.getMessage());
            return errorResponse;
        }
    }
}
