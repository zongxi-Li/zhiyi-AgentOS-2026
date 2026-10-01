package com.kinlin.ai.projection.conversation;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.kinlin.ai.entity.Conversation;
import com.kinlin.ai.projection.conversation.dto.ConversationDetailQuery;
import com.kinlin.ai.projection.conversation.dto.ConversationQuery;
import com.kinlin.ai.projection.conversation.mapper.ConversationProjectionMapper;
import org.junit.jupiter.api.Test;

import java.time.LocalDateTime;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.*;

/** Field-closure and time-format checks for the conversation query projection. */
class ConversationProjectionSerializationTest {

    private static final LocalDateTime CREATED = LocalDateTime.of(2026, 9, 30, 8, 30, 15);
    private static final LocalDateTime UPDATED = LocalDateTime.of(2026, 10, 1, 9, 0, 0);

    /** Mirrors JacksonConfig: JavaTimeModule + ISO strings, so DTOs match the legacy entity wire format. */
    private final ObjectMapper jackson = new ObjectMapper()
            .registerModule(new JavaTimeModule())
            .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);

    @Test
    void queryExposesExactlyTheLegacyConversationFields() throws Exception {
        Conversation entity = new Conversation();
        entity.setId(UUID.fromString("00000000-0000-0000-0000-000000000001"));
        entity.setUserId(UUID.fromString("00000000-0000-0000-0000-000000000002"));
        entity.setRoleId(UUID.fromString("00000000-0000-0000-0000-000000000003"));
        entity.setContextId("ctx_1");
        entity.setTitle("标题");
        entity.setWorkspaceMode("agent");
        entity.setPreview("预览文本");
        entity.setCreatedAt(CREATED);
        entity.setUpdatedAt(UPDATED);

        JsonNode json = jackson.readTree(jackson.writeValueAsString(ConversationProjectionMapper.toQuery(entity)));
        assertEquals("00000000-0000-0000-0000-000000000001", json.get("id").asText());
        assertEquals("00000000-0000-0000-0000-000000000002", json.get("userId").asText());
        assertEquals("00000000-0000-0000-0000-000000000003", json.get("roleId").asText());
        assertEquals("ctx_1", json.get("contextId").asText());
        assertEquals("标题", json.get("title").asText());
        assertEquals("agent", json.get("workspaceMode").asText());
        assertEquals("预览文本", json.get("preview").asText());
        assertEquals("2026-09-30T08:30:15", json.get("createdAt").asText());
        assertEquals("2026-10-01T09:00:00", json.get("updatedAt").asText());
        assertEquals(9, json.size(), "field set must stay the closed whitelist");
        for (String field : java.util.List.of("id", "userId", "roleId", "contextId", "title",
                "workspaceMode", "preview", "createdAt", "updatedAt")) {
            assertTrue(json.has(field), field + " must stay in the response");
        }
    }

    @Test
    void nullOptionalFieldsSerializeAsNullsWithoutChangingTheShape() throws Exception {
        ConversationQuery query = new ConversationQuery(null, null, null, null, null, null, null, null, null);
        JsonNode json = jackson.readTree(jackson.writeValueAsString(query));
        assertEquals(9, json.size());
        json.forEach(field -> assertTrue(field.isNull(), "absent values stay explicit nulls, not dropped keys"));
        ConversationDetailQuery detail = ConversationProjectionMapper.toDetail(new Conversation(), null);
        assertTrue(jackson.readTree(jackson.writeValueAsString(detail)).get("preview").isNull());
    }

    @Test
    void detailKeepsTheEnvelopeContractTyped() {
        Conversation entity = new Conversation();
        entity.setContextId("ctx_detail");
        ConversationDetailQuery detail = ConversationProjectionMapper.toDetail(entity, "首条消息");
        assertInstanceOf(ConversationQuery.class, detail.conversation());
        assertEquals("ctx_detail", detail.conversation().contextId());
        assertEquals("首条消息", detail.preview());
    }
}
