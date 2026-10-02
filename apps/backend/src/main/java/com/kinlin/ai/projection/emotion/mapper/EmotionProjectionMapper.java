package com.kinlin.ai.projection.emotion.mapper;

import java.util.Map;
import com.kinlin.ai.projection.emotion.dto.EmotionQuery;
import com.kinlin.ai.projection.emotion.dto.EmotionResponseQuery;
import static com.kinlin.ai.projection.common.mapper.QueryWire.*;

/** Whitelist of emotionawareservice.py outputs; no analysis, calls or fallback decisions. */
public final class EmotionProjectionMapper {
    private EmotionProjectionMapper() { }
    public static EmotionQuery analyze(Map<String, Object> wire) {
        return emotion(wire);
    }
    private static EmotionQuery emotion(Map<?, ?> wire) {
        return new EmotionQuery(text(wire, "emotion"), decimal(wire, "intensity"), decimal(wire, "confidence"));
    }
    public static EmotionResponseQuery response(Map<String, Object> wire) {
        if (wire.containsKey("error")) {
            return new EmotionResponseQuery(null, null, null, null, text(wire, "error"));
        }
        Map<?, ?> animation = wire.get("animation") == null ? null : object(wire.get("animation"));
        return new EmotionResponseQuery(text(wire, "text"), animation == null ? null
                : new EmotionResponseQuery.AnimationQuery(text(animation, "expression"), text(animation, "gesture"),
                        decimal(animation, "intensity"), decimal(animation, "duration")),
                wire.get("emotion") == null ? null : emotion(object(wire.get("emotion"))),
                wire.get("user_emotion") == null ? null : emotion(object(wire.get("user_emotion"))), null);
    }
}
