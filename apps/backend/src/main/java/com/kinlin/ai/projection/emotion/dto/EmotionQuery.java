package com.kinlin.ai.projection.emotion.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record EmotionQuery(String emotion, Double intensity, Double confidence) implements QueryResponse { }
