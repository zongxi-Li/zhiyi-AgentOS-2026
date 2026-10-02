package com.kinlin.ai.projection.digitalhuman.mapper;

import java.util.Map;
import com.kinlin.ai.dto.DigitalHumanResponse;
import com.kinlin.ai.projection.digitalhuman.dto.DigitalHumanQuery;
import com.kinlin.ai.projection.digitalhuman.dto.DigitalHumanQuery.*;
import static com.kinlin.ai.projection.common.mapper.QueryWire.*;

/** Public avatar whitelist from digitalhumanservice.py; internal paths/prompts/settings are not copied. */
public final class DigitalHumanProjectionMapper {
    private DigitalHumanProjectionMapper() { }
    public static DigitalHumanQuery query(DigitalHumanResponse result) {
        if (result == null) { return null; }
        return new DigitalHumanQuery(result.getSuccess(),
                result.getData() == null ? null : avatar(result.getData()), result.getMessage());
    }
    private static AvatarQuery avatar(Map<?, ?> raw) {
        return new AvatarQuery(text(raw, "avatar_id"), text(raw, "role_id"), text(raw, "modelUrl"),
                text(raw, "modelPath"), text(raw, "style"), text(raw, "status"), text(raw, "created_at"),
                text(raw, "name"), text(raw, "description"), text(raw, "image_url"), text(raw, "image_base64"),
                text(raw, "local_image_url"), text(raw, "avatar"), config(raw.get("avatar_config")),
                expressions(raw.get("expressions")), animations(raw.get("animations")));
    }
    private static AvatarConfigQuery config(Object value) {
        if (value == null) { return null; }
        Map<?, ?> raw = object(value);
        Map<?, ?> appearance = raw.get("appearance") == null ? null : object(raw.get("appearance"));
        return new AvatarConfigQuery(text(raw, "model_type"), text(raw, "gender"), text(raw, "age_range"),
                appearance == null ? null : new AppearanceQuery(text(appearance, "hair_style"),
                        text(appearance, "clothing"), appearance.get("accessories") == null ? null
                                : texts(appearance.get("accessories"))),
                text(raw, "render_style"), decimal(raw, "exaggeration"));
    }
    private static ExpressionsQuery expressions(Object value) {
        if (value == null) { return null; }
        Map<?, ?> raw = object(value);
        return new ExpressionsQuery(expression(raw.get("neutral")), expression(raw.get("happy")),
                expression(raw.get("sad")), expression(raw.get("angry")),
                expression(raw.get("surprised")), expression(raw.get("confused")));
    }
    private static ExpressionQuery expression(Object value) {
        if (value == null) { return null; }
        Map<?, ?> raw = object(value);
        return new ExpressionQuery(decimal(raw, "intensity"), text(raw, "mouth"), text(raw, "eyes"));
    }
    private static AnimationsQuery animations(Object value) {
        if (value == null) { return null; }
        Map<?, ?> raw = object(value);
        return new AnimationsQuery(animation(raw.get("idle")), animation(raw.get("speaking")),
                animation(raw.get("nodding")), animation(raw.get("gesturing")));
    }
    private static AnimationQuery animation(Object value) {
        if (value == null) { return null; }
        Map<?, ?> raw = object(value);
        return new AnimationQuery(decimal(raw, "duration"), bool(raw, "loop"));
    }
}
