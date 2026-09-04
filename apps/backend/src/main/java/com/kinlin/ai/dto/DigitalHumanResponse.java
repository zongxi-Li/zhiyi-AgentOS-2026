package com.kinlin.ai.dto;

import lombok.Data;
import java.util.Map;

/**
 * 数字人响应DTO
 */
@Data
public class DigitalHumanResponse {
    private Boolean success;
    private Map<String, Object> data;
    private String message;
}

