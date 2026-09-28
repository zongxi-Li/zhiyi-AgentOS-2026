package com.kinlin.ai.client;

import com.kinlin.ai.dto.EmotionAnalyzeRequest;
import com.kinlin.ai.dto.EmotionAwareResponseRequest;

import java.util.Map;

/**
 * What the Java platform needs from the Python emotion-awareness capability
 * ({@code /ai/emotion/**} family). Emotion payloads stay dynamic {@code Map}
 * projections; the {@code success/data} envelope is unwrapped here.
 */
public interface EmotionClient {

    Map<String, Object> analyzeEmotion(EmotionAnalyzeRequest request);

    Map<String, Object> generateEmotionAwareResponse(EmotionAwareResponseRequest request);
}
