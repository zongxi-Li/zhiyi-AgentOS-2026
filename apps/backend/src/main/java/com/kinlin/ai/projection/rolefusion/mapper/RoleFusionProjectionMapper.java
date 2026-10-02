package com.kinlin.ai.projection.rolefusion.mapper;

import java.util.List;
import java.util.Map;
import com.kinlin.ai.projection.rolefusion.dto.RoleFusionQuery;
import static com.kinlin.ai.projection.common.mapper.QueryWire.*;

/** Pure representation of rolefusionservice.py's public fusion/style/association results. */
public final class RoleFusionProjectionMapper {
    private RoleFusionProjectionMapper() { }
    public static RoleFusionQuery query(Map<String, Object> wire) {
        if (wire.containsKey("error")) {
            return new RoleFusionQuery(null, null, null, null, null, text(wire, "error"));
        }
        Map<?, ?> style = wire.get("style") == null ? null : object(wire.get("style"));
        return new RoleFusionQuery(text(wire, "response"), style == null ? null
                : new RoleFusionQuery.StyleQuery(decimal(style, "formality"), decimal(style, "warmth"),
                        decimal(style, "technical_level")),
                weights(wire.get("weights")), sources(wire.get("sources")), text(wire, "question"), null);
    }
    private static List<RoleFusionQuery.WeightQuery> weights(Object wire) {
        if (wire == null) { return null; }
        return object(wire).entrySet().stream().map(entry -> {
            if (!(entry.getKey() instanceof String roleId) || !(entry.getValue() instanceof Number weight)
                    || !Double.isFinite(weight.doubleValue())) { throw invalid(); }
            return new RoleFusionQuery.WeightQuery(roleId, weight.doubleValue());
        }).toList();
    }
    private static List<RoleFusionQuery.SourceQuery> sources(Object wire) {
        if (wire == null) { return null; }
        return object(wire).entrySet().stream().map(entry -> {
            if (!(entry.getKey() instanceof String roleId) || !(entry.getValue() instanceof String response)) {
                throw invalid();
            }
            return new RoleFusionQuery.SourceQuery(roleId, response);
        }).toList();
    }
}
