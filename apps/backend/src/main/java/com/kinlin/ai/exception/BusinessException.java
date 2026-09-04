package com.kinlin.ai.exception;

import lombok.Getter;

/**
 * 业务异常类
 */
@Getter
public class BusinessException extends RuntimeException {

    private final String code;
    private final Object[] args;

    public BusinessException(String message) {
        super(message);
        this.code = "BUSINESS_ERROR";
        this.args = new Object[0];
    }

    public BusinessException(String code, String message) {
        super(message);
        this.code = code;
        this.args = new Object[0];
    }

    public BusinessException(String code, String message, Object... args) {
        super(message);
        this.code = code;
        this.args = args;
    }
}

