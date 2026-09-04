package com.kinlin.ai.dto;

import lombok.Data;

import java.util.UUID;

/**
 * 登录响应DTO
 */
@Data
public class LoginResponse {

    private String token;

    private UUID userId;

    private String username;

    private String message;
}

