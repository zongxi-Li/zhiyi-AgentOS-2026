package com.kinlin.ai.projection.feedback;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.kinlin.ai.entity.UserFeedback;
import com.kinlin.ai.projection.feedback.dto.FeedbackQuery;
import com.kinlin.ai.projection.feedback.mapper.FeedbackProjectionMapper;
import org.junit.jupiter.api.Test;

import java.time.LocalDateTime;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.*;

class FeedbackProjectionSerializationTest {

    private final ObjectMapper jackson = new ObjectMapper()
            .registerModule(new JavaTimeModule())
            .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);

    @Test
    void projectionKeepsTheExactPublicWireShapeOfTheLegacyEntityResponse() throws Exception {
        UserFeedback feedback = feedback(true);
        String entityJson = jackson.writeValueAsString(feedback);
        String projectedJson = jackson.writeValueAsString(FeedbackProjectionMapper.toQuery(feedback));
        assertEquals(jackson.readTree(entityJson), jackson.readTree(projectedJson),
                "投影必须与旧实体响应逐字段一致（键序无关）");

        JsonNode json = jackson.readTree(projectedJson);
        Set<String> actual = new HashSet<>();
        json.fieldNames().forEachRemaining(actual::add);
        assertEquals(Set.of("id", "userId", "conversationId", "messageId", "roleId",
                "feedbackType", "rating", "content", "sentiment", "createdAt"), actual);
        assertEquals("2026-10-01T09:00:00", json.get("createdAt").asText());
    }

    @Test
    void optionalReferencesRatingsAndSentimentStayNullInsteadOfFabricated() throws Exception {
        FeedbackQuery query = FeedbackProjectionMapper.toQuery(feedback(false));
        assertNull(query.conversationId());
        assertNull(query.messageId());
        assertNull(query.roleId());
        assertNull(query.rating());
        assertNull(query.sentiment());
        JsonNode json = jackson.readTree(jackson.writeValueAsString(query));
        assertTrue(json.get("conversationId").isNull());
        assertTrue(json.get("sentiment").isNull());
    }

    @Test
    void listProjectionKeepsServiceOrderAndRowsAreSnapshots() {
        UserFeedback first = feedback(true);
        UserFeedback second = feedback(false);
        List<FeedbackQuery> projected = FeedbackProjectionMapper.toQuery(List.of(first, second));
        assertEquals(List.of(first.getId(), second.getId()),
                projected.stream().map(FeedbackQuery::id).toList());
        String originalContent = first.getContent();
        first.setContent("映射后被修改的正文");
        assertEquals(originalContent, projected.get(0).content(), "投影行是取值快照，不追踪实体后续修改");
    }

    private UserFeedback feedback(boolean fullyPopulated) {
        UserFeedback feedback = new UserFeedback();
        feedback.setId(UUID.randomUUID());
        feedback.setUserId(UUID.randomUUID());
        if (fullyPopulated) {
            feedback.setConversationId(UUID.randomUUID());
            feedback.setMessageId(UUID.randomUUID());
            feedback.setRoleId(UUID.randomUUID());
            feedback.setRating(5);
            feedback.setSentiment("positive");
        }
        feedback.setFeedbackType("quality");
        feedback.setContent("回答很准确，长文本不截断：" + "赞".repeat(300));
        feedback.setCreatedAt(LocalDateTime.of(2026, 10, 1, 9, 0, 0));
        return feedback;
    }
}
