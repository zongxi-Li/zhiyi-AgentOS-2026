package com.kinlin.ai.dto;

import lombok.Data;
import java.util.Map;

/**
 * 情感分析请求DTO
 */
@Data
public class EmotionAnalyzeRequest {
    private String text;
    private Map<String, Object> audioFeatures;
    private Map<String, Object> facialFeatures;
}

