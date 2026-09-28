package com.kinlin.ai.infrastructure.http;

import com.kinlin.ai.client.EmotionClient;
import com.kinlin.ai.dto.EmotionAnalyzeRequest;
import com.kinlin.ai.dto.EmotionAwareResponseRequest;
import org.springframework.stereotype.Component;

import java.util.HashMap;
import java.util.Map;

/**
 * WebClient implementation of the emotion-awareness capability
 * ({@code /ai/emotion/**} family). Unwraps the upstream {@code success/data}
 * envelope; emotion payloads stay dynamic maps.
 */
@Component
public class WebClientEmotionClient implements EmotionClient {

    private final PlatformAiTransport transport;

    public WebClientEmotionClient(PlatformAiTransport transport) {
        this.transport = transport;
    }

    @Override
    public Map<String, Object> analyzeEmotion(EmotionAnalyzeRequest request) {
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

        return unwrap(transport.postJson("/ai/emotion/analyze", requestBody, TransportTypes.MAP));
    }

    @Override
    public Map<String, Object> generateEmotionAwareResponse(EmotionAwareResponseRequest request) {
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

        return unwrap(transport.postJson("/ai/emotion/response", requestBody, TransportTypes.MAP));
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> unwrap(Map<String, Object> responseMap) {
        if (responseMap != null && Boolean.TRUE.equals(responseMap.get("success"))) {
            return (Map<String, Object>) responseMap.get("data");
        }
        return new HashMap<>();
    }
}
