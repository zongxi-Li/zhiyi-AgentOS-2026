package com.kinlin.ai.projection.common.mapper;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import java.util.function.Function;

/** Read-only wire parsing helpers. Public DTOs are explicitly constructed by their domain mappers. */
public final class QueryWire {
    private QueryWire() { }
    public static Map<?, ?> object(Object value) {
        if (value instanceof Map<?, ?> map) { return map; }
        throw invalid();
    }
    public static Map<?, ?> optionalObject(Object value) { return value == null ? Map.of() : object(value); }
    public static String text(Map<?, ?> source, String key) {
        Object value = source.get(key);
        if (value == null) { return null; }
        if (value instanceof String text) { return text; }
        throw invalid();
    }
    public static String requiredText(Map<?, ?> source, String key) {
        String result = text(source, key);
        if (result == null || result.isBlank()) { throw invalid(); }
        return result;
    }
    public static Long integer(Map<?, ?> source, String key) {
        Object value = source.get(key);
        if (value == null) { return null; }
        if (value instanceof Number number) { return new BigDecimal(number.toString()).longValueExact(); }
        throw invalid();
    }
    public static Integer smallInt(Map<?, ?> source, String key) {
        Long value = integer(source, key);
        return value == null ? null : Math.toIntExact(value);
    }
    public static int requiredInt(Map<?, ?> source, String key) {
        Integer result = smallInt(source, key);
        if (result == null) { throw invalid(); }
        return result;
    }
    public static Double decimal(Map<?, ?> source, String key) {
        Object value = source.get(key);
        if (value == null) { return null; }
        if (value instanceof Number number && Double.isFinite(number.doubleValue())) { return number.doubleValue(); }
        throw invalid();
    }
    public static Boolean bool(Map<?, ?> source, String key) {
        Object value = source.get(key);
        if (value == null) { return null; }
        if (value instanceof Boolean result) { return result; }
        throw invalid();
    }
    public static List<?> list(Object value) {
        if (value == null) { return List.of(); }
        if (value instanceof List<?> list) { return list; }
        throw invalid();
    }
    public static List<String> texts(Object value) {
        return list(value).stream().map(item -> {
            if (item instanceof String text) { return text; }
            throw invalid();
        }).toList();
    }
    public static <T> List<T> items(Object value, Function<Map<?, ?>, T> mapper) {
        return list(value).stream().map(item -> mapper.apply(object(item))).toList();
    }
    public static IllegalArgumentException invalid() { return new IllegalArgumentException("Invalid query response contract"); }
}
