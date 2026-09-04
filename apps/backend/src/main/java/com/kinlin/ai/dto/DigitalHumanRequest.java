package com.kinlin.ai.dto;

import lombok.Data;
import java.util.Map;

/**
 * 数字人创建请求DTO
 */
@Data
public class DigitalHumanRequest {
    private String roleId;
    private String personality;
    private String profession;
    private String style = "realistic";
}

