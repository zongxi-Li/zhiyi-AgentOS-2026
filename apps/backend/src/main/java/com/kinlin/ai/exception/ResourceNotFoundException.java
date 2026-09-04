package com.kinlin.ai.exception;

/**
 * 资源未找到异常
 */
public class ResourceNotFoundException extends BusinessException {

    public ResourceNotFoundException(String resourceName, Object id) {
        super("RESOURCE_NOT_FOUND", 
            String.format("%s with id %s not found", resourceName, id));
    }

    public ResourceNotFoundException(String message) {
        super("RESOURCE_NOT_FOUND", message);
    }
}

