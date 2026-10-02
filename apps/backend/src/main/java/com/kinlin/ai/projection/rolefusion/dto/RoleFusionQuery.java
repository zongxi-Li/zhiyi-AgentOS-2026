package com.kinlin.ai.projection.rolefusion.dto;

import java.util.List;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/** Dynamic role IDs are association values, never property names. */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record RoleFusionQuery(String response, StyleQuery style, List<WeightQuery> weights,
        List<SourceQuery> sources, String question, String error) implements QueryResponse {
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record StyleQuery(Double formality, Double warmth,
            @JsonProperty("technical_level") Double technicalLevel) { }
    public record WeightQuery(String roleId, Double weight) { }
    public record SourceQuery(String roleId, String response) { }
}
