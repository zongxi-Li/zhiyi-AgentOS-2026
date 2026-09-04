package com.kinlin.ai.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

import java.util.Map;

/**
 * 角色创建请求DTO
 */
@Data
public class RoleCreateRequest {

    @NotBlank(message = "角色名称不能为空")
    private String name;

    private String description;

    @NotBlank(message = "系统提示词不能为空")
    private String systemPrompt;

    private Map<String, Object> dialogueStyle;

    private Map<String, Object> personality;

    private Map<String, Object> avatarConfig;
}

