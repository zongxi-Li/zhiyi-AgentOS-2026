package com.kinlin.ai.util;

import java.util.UUID;

/**
 * ID生成工具类
 */
public class IdGenerator {

    /**
     * 生成UUID字符串
     */
    public static String generateUUID() {
        return UUID.randomUUID().toString();
    }

    /**
     * 生成短ID（用于contextId等）
     */
    public static String generateShortId() {
        return UUID.randomUUID().toString().replace("-", "").substring(0, 16);
    }
}

