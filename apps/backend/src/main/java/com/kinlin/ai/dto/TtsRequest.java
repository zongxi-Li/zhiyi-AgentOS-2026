package com.kinlin.ai.dto;

import lombok.Data;

/**
 * 语音合成请求DTO
 */
@Data
public class TtsRequest {

    private String text;

    private String voice = "default";

    private Double speed = 1.0;

    private Double pitch = 1.0;
}

