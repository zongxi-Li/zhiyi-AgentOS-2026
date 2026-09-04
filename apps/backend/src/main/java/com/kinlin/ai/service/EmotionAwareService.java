package com.kinlin.ai.service;

import com.kinlin.ai.dto.EmotionAnalyzeRequest;
import com.kinlin.ai.dto.EmotionAwareResponseRequest;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.time.Duration;
import java.util.HashMap;
import java.util.Map;

/**
 * 情感感知服务
 * 负责与Python AI服务的情感感知功能通信
 */
@Slf4j
@Service
public class EmotionAwareService {

    private final WebClient webClient;

    @Value("${ai.service.url}")
    private String aiServiceUrl;

    @Value("${ai.service.timeout}")
    private int timeout;

    public EmotionAwareService(WebClient.Builder webClientBuilder, 
                               @Value("${ai.service.url}") String aiServiceUrl, 
                               @Value("${ai.service.timeout}") int timeout) {
        this.aiServiceUrl = aiServiceUrl;
        this.timeout = timeout;
        this.webClient = webClientBuilder
                .baseUrl(aiServiceUrl)
                .build();
    }

    /**
     * 多模态情感分析
     */
    public Map<String, Object> analyzeEmotion(EmotionAnalyzeRequest request) {
        try {
            Map<String, Object> requestBody = new HashMap<>();
            if (request.getText() != null) {
                requestBody.put("text", request.getText());
            }
            if (request.getAudioFeatures() != null) {
                requestBody.put("audio_features", request.getAudioFeatures());
            }
            if (request.getFacialFeatures() != null) {
                requestBody.put("facial_features", request.getFacialFeatures());
            }

            Map<String, Object> responseMap = webClient.post()
                    .uri("/ai/emotion/analyze")
                    .bodyValue(requestBody)
                    .retrieve()
                    .bodyToMono(Map.class)
                    .timeout(Duration.ofMillis(timeout))
                    .block();

            if (responseMap != null && Boolean.TRUE.equals(responseMap.get("success"))) {
                return (Map<String, Object>) responseMap.get("data");
            }
            return new HashMap<>();
        } catch (Exception e) {
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
            Map<String, Object> requestBody = new HashMap<>();
            requestBody.put("question", request.getQuestion());
            requestBody.put("base_role", request.getBaseRole());
            if (request.getText() != null) {
                requestBody.put("text", request.getText());
            }
            if (request.getAudioFeatures() != null) {
                requestBody.put("audio_features", request.getAudioFeatures());
            }
            if (request.getFacialFeatures() != null) {
                requestBody.put("facial_features", request.getFacialFeatures());
            }
            if (request.getUserEmotion() != null) {
                requestBody.put("user_emotion", request.getUserEmotion());
            }

            Map<String, Object> responseMap = webClient.post()
                    .uri("/ai/emotion/response")
                    .bodyValue(requestBody)
                    .retrieve()
                    .bodyToMono(Map.class)
                    .timeout(Duration.ofMillis(timeout))
                    .block();

            if (responseMap != null && Boolean.TRUE.equals(responseMap.get("success"))) {
                return (Map<String, Object>) responseMap.get("data");
            }
            return new HashMap<>();
        } catch (Exception e) {
            log.error("生成情感感知回复失败", e);
            Map<String, Object> errorResponse = new HashMap<>();
            errorResponse.put("error", "生成情感感知回复失败: " + e.getMessage());
            return errorResponse;
        }
    }
}

