package com.kinlin.ai.dto;

import lombok.Data;

/**
 * 语音识别响应DTO
 */
@Data
public class VoiceRecognitionResponse {

    private String text;

    private Double confidence;

    private Double duration;
}

