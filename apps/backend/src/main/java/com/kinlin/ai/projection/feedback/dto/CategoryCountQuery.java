package com.kinlin.ai.projection.feedback.dto;

/**
 * 反馈分类计数。feedbackType 为自由字符串列（自定义分类是真实输入），
 * 因此动态键分类以显式列表承载而非 Map：type 为原样分类键，count 为该分类计数。
 */
public record CategoryCountQuery(String type, long count) { }
