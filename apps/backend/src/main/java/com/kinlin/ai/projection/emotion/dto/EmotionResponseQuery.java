package com.kinlin.ai.projection.emotion.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.kinlin.ai.projection.common.dto.QueryResponse;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record EmotionResponseQuery(String text, AnimationQuery animation, EmotionQuery emotion,
        @JsonProperty("user_emotion") EmotionQuery userEmotion, String error) implements QueryResponse {
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record AnimationQuery(String expression, String gesture, Double intensity, Double duration) { }
}
