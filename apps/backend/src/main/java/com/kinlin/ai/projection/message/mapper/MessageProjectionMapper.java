package com.kinlin.ai.projection.message.mapper;

import com.kinlin.ai.entity.Message;
import com.kinlin.ai.projection.message.dto.MessageMetadataQuery;
import com.kinlin.ai.projection.message.dto.MessageQuery;
import com.kinlin.ai.projection.message.dto.MessageRoleQuery;
import com.kinlin.ai.projection.message.dto.MessageTypeQuery;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Pure output adapter over persisted messages; no service, repository, transport or
 * cache calls. Metadata keeps only the whitelisted public keys; optional fields whose
 * persisted value has an unexpected JSON type are omitted (null) instead of coerced.
 */
public final class MessageProjectionMapper {
    private MessageProjectionMapper() { }

    public static MessageQuery toQuery(Message message) {
        return new MessageQuery(message.getId(), message.getConversationId(),
                message.getRole() == null ? null : MessageRoleQuery.valueOf(message.getRole().name()),
                message.getContent(),
                message.getMessageType() == null ? null : MessageTypeQuery.valueOf(message.getMessageType().name()),
                message.getFileUrl(),
                metadata(message.getMetadata()),
                message.getCreatedAt());
    }

    public static List<MessageQuery> toQuery(List<Message> messages) {
        List<MessageQuery> projected = new ArrayList<>(messages.size());
        for (Message message : messages) {
            projected.add(toQuery(message));
        }
        return projected;
    }

    private static MessageMetadataQuery metadata(Map<String, Object> source) {
        if (source == null || source.isEmpty()) {
            return null;
        }
        return new MessageMetadataQuery(
                decimal(source.get("confidence")),
                whole(source.get("tokens_used")),
                whole(source.get("totalTokens")),
                text(source.get("effectiveModel")),
                text(source.get("model_info")),
                text(source.get("requestedThinkingMode")),
                text(source.get("effectiveThinkingMode")),
                text(source.get("effectiveReasoningEffort")),
                whole(source.get("reasoningPhaseMs")),
                whole(source.get("inputTokens")),
                whole(source.get("reasoningTokens")),
                whole(source.get("outputTokens")),
                whole(source.get("latencyMs")),
                flag(source.get("thinkingEnabled")),
                stages(source.get("executionSummary")));
    }

    private static Double decimal(Object value) {
        return value instanceof Number number ? number.doubleValue() : null;
    }

    private static Long whole(Object value) {
        return value instanceof Number number && !(value instanceof Double) && !(value instanceof Float)
                ? number.longValue()
                : null;
    }

    private static String text(Object value) {
        return value instanceof String string ? string : null;
    }

    private static Boolean flag(Object value) {
        return value instanceof Boolean bool ? bool : null;
    }

    private static List<MessageMetadataQuery.ExecutionStageQuery> stages(Object value) {
        if (!(value instanceof List<?> items)) {
            return null;
        }
        List<MessageMetadataQuery.ExecutionStageQuery> stages = new ArrayList<>(items.size());
        for (Object item : items) {
            if (item instanceof Map<?, ?> stage
                    && stage.get("stage") instanceof String stageName
                    && stage.get("status") instanceof String status
                    && stage.get("description") instanceof String description) {
                stages.add(new MessageMetadataQuery.ExecutionStageQuery(stageName, status, description));
            }
        }
        return stages.isEmpty() ? null : stages;
    }
}
