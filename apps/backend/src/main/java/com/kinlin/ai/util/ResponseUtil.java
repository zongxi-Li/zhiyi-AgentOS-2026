package com.kinlin.ai.util;

import lombok.Data;

/**
 * 统一响应工具类
 */
public class ResponseUtil {

    public static <T> Response<T> success(T data) {
        return new Response<>(true, "操作成功", data);
    }

    public static <T> Response<T> success(String message, T data) {
        return new Response<>(true, message, data);
    }

    public static <T> Response<T> error(String message) {
        return new Response<>(false, message, null);
    }

    @Data
    public static class Response<T> {
        private boolean success;
        private String message;
        private T data;

        public Response(boolean success, String message, T data) {
            this.success = success;
            this.message = message;
            this.data = data;
        }
    }
}

