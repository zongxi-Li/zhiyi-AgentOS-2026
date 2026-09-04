package com.kinlin.ai.dto;

import lombok.Data;
import java.util.Map;

/**
 * 情感感知回复请求DTO
 */
@Data
public class EmotionAwareResponseRequest {
    private String question;
    private Map<String, Object> baseRole;
    private String text;
    private Map<String, Object> audioFeatures;
    private Map<String, Object> facialFeatures;
    private Map<String, Object> userEmotion;
}

