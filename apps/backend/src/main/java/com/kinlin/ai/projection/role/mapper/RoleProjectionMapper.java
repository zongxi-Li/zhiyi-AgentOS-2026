package com.kinlin.ai.projection.role.mapper;

import com.kinlin.ai.entity.Role;
import com.kinlin.ai.projection.role.dto.RoleConfigurationQuery;
import com.kinlin.ai.projection.role.dto.RoleContextQuery;
import com.kinlin.ai.projection.role.dto.RoleKind;
import com.kinlin.ai.projection.role.dto.RoleQuery;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

/** Pure output adapter over service results; no service, repository, transport or cache calls. */
public final class RoleProjectionMapper {
    private RoleProjectionMapper() { }

    public static RoleQuery toQuery(Role role) {
        return new RoleQuery(role.getId(), role.getName(), role.getDescription(),
                role.getRoleType() == null ? null : RoleKind.valueOf(role.getRoleType().name()),
                role.getUserId(), role.getStableKey(), role.getSystemPrompt(),
                configuration(role.getDialogueStyle()), configuration(role.getPersonality()),
                configuration(role.getAvatarConfig()), role.getCreatedAt(), role.getUpdatedAt());
    }

    public static RoleContextQuery toContext(Map<String, Object> context) {
        return new RoleContextQuery((String) context.get("role_id"), (String) context.get("name"),
                (String) context.get("description"), configuration(context.get("personality")),
                (String) context.get("system_prompt"), configuration(context.get("dialogue_style")));
    }

    private static RoleConfigurationQuery configuration(Object value) {
        if (value == null) { return null; }
        if (value instanceof Map<?, ?> object) {
            return new RoleConfigurationQuery(properties(object));
        }
        throw new IllegalArgumentException("Role configuration must be a JSON object");
    }

    private static List<RoleConfigurationQuery.Property> properties(Map<?, ?> object) {
        return object.entrySet().stream().map(entry -> {
            if (!(entry.getKey() instanceof String name)) {
                throw new IllegalArgumentException("Role configuration keys must be strings");
            }
            return new RoleConfigurationQuery.Property(name, value(entry.getValue()));
        }).toList();
    }

    private static RoleConfigurationQuery.Value value(Object source) {
        if (source == null) { return new RoleConfigurationQuery.NullValue(); }
        if (source instanceof String text) { return new RoleConfigurationQuery.TextValue(text); }
        if (source instanceof Boolean bool) { return new RoleConfigurationQuery.BooleanValue(bool); }
        if (source instanceof Number number) {
            return new RoleConfigurationQuery.NumericValue(new BigDecimal(number.toString()));
        }
        if (source instanceof List<?> items) {
            return new RoleConfigurationQuery.ArrayValue(items.stream().map(RoleProjectionMapper::value).toList());
        }
        if (source instanceof Map<?, ?> object) {
            return new RoleConfigurationQuery.PropertiesValue(properties(object));
        }
        throw new IllegalArgumentException("Unsupported role configuration value");
    }
}
