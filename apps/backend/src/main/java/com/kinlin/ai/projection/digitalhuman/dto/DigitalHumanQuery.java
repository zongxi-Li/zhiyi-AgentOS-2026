package com.kinlin.ai.projection.digitalhuman.dto;

import java.util.List;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/** Query-only boundary; the three envelope keys keep the existing null/error representation. */
public record DigitalHumanQuery(Boolean success, AvatarQuery data, String message) implements QueryResponse {
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record AvatarQuery(@JsonProperty("avatar_id") String avatarId, @JsonProperty("role_id") String roleId,
            String modelUrl, String modelPath, String style, String status,
            @JsonProperty("created_at") String createdAt, String name, String description,
            @JsonProperty("image_url") String imageUrl, @JsonProperty("image_base64") String imageBase64,
            @JsonProperty("local_image_url") String localImageUrl, String avatar,
            @JsonProperty("avatar_config") AvatarConfigQuery avatarConfig,
            ExpressionsQuery expressions, AnimationsQuery animations) { }
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record AvatarConfigQuery(@JsonProperty("model_type") String modelType, String gender,
            @JsonProperty("age_range") String ageRange, AppearanceQuery appearance,
            @JsonProperty("render_style") String renderStyle, Double exaggeration) { }
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record AppearanceQuery(@JsonProperty("hair_style") String hairStyle, String clothing,
            List<String> accessories) { }
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record ExpressionsQuery(ExpressionQuery neutral, ExpressionQuery happy, ExpressionQuery sad,
            ExpressionQuery angry, ExpressionQuery surprised, ExpressionQuery confused) { }
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record ExpressionQuery(Double intensity, String mouth, String eyes) { }
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record AnimationsQuery(AnimationQuery idle, AnimationQuery speaking, AnimationQuery nodding,
            AnimationQuery gesturing) { }
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record AnimationQuery(Double duration, Boolean loop) { }
}
