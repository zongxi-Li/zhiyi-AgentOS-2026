package com.kinlin.ai.service;

import com.kinlin.ai.client.EmotionClient;
import com.kinlin.ai.client.PlatformAiClientException;
import com.kinlin.ai.dto.EmotionAnalyzeRequest;
import com.kinlin.ai.dto.EmotionAwareResponseRequest;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.HashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.when;

/**
 * EmotionAwareService单元测试（应用层 fallback 表征：transport 失败时的既有用户可见行为）
 */
@ExtendWith(MockitoExtension.class)
class EmotionAwareServiceTest {

    @Mock
    private EmotionClient emotionClient;

    private EmotionAwareService emotionAwareService;

    @BeforeEach
    void setUp() {
        emotionAwareService = new EmotionAwareService(emotionClient);
    }

    @Test
    void testAnalyzeEmotion_Success() {
        // Arrange
        EmotionAnalyzeRequest request = new EmotionAnalyzeRequest();
        request.setText("我很开心");

        when(emotionClient.analyzeEmotion(request))
                .thenReturn(Map.of("emotion", "happy", "intensity", 0.8));

        // Act
        Map<String, Object> result = emotionAwareService.analyzeEmotion(request);

        // Assert
        assertNotNull(result);
        assertEquals("happy", result.get("emotion"));
    }

    @Test
    void testAnalyzeEmotion_TransportFailureKeepsNeutralFallback() {
        // Arrange：表征冻结——情感分析失败时返回中性情感默认值
        EmotionAnalyzeRequest request = new EmotionAnalyzeRequest();
        request.setText("测试");

        when(emotionClient.analyzeEmotion(request))
                .thenThrow(new PlatformAiClientException(
                        PlatformAiClientException.Type.UPSTREAM_ERROR, "500 Service Unavailable"));

        // Act
        Map<String, Object> result = emotionAwareService.analyzeEmotion(request);

        // Assert
        assertNotNull(result);
        assertEquals("neutral", result.get("emotion"));
        assertEquals(0.5, result.get("intensity"));
    }

    @Test
    void testGenerateEmotionAwareResponse_Success() {
        // Arrange
        EmotionAwareResponseRequest request = new EmotionAwareResponseRequest();
        request.setQuestion("你好");
        request.setBaseRole(new HashMap<>());

        when(emotionClient.generateEmotionAwareResponse(request))
                .thenReturn(Map.of("response", "你好，很高兴见到你"));

        // Act
        Map<String, Object> result = emotionAwareService.generateEmotionAwareResponse(request);

        // Assert
        assertNotNull(result);
        assertEquals("你好，很高兴见到你", result.get("response"));
    }

    @Test
    void testGenerateEmotionAwareResponse_TransportFailureKeepsFrozenErrorMap() {
        // Arrange：表征冻结——error Map 携带既有前缀文案
        EmotionAwareResponseRequest request = new EmotionAwareResponseRequest();
        request.setQuestion("你好");
        request.setBaseRole(new HashMap<>());

        when(emotionClient.generateEmotionAwareResponse(request))
                .thenThrow(new PlatformAiClientException(
                        PlatformAiClientException.Type.UNAVAILABLE, "Connection refused"));

        // Act
        Map<String, Object> result = emotionAwareService.generateEmotionAwareResponse(request);

        // Assert
        assertEquals("生成情感感知回复失败: Connection refused", result.get("error"));
    }
}
