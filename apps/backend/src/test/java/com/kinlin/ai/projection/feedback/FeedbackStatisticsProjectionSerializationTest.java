package com.kinlin.ai.projection.feedback;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.kinlin.ai.projection.feedback.dto.FeedbackReceiptQuery;
import com.kinlin.ai.projection.feedback.dto.UserFeedbackStatisticsQuery;
import com.kinlin.ai.projection.feedback.mapper.FeedbackStatisticsProjectionMapper;
import com.kinlin.ai.service.UserFeedbackService;
import org.junit.jupiter.api.Test;

import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.*;

class FeedbackStatisticsProjectionSerializationTest {

    private final ObjectMapper jackson = new ObjectMapper()
            .registerModule(new JavaTimeModule())
            .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);

    @Test
    void userStatisticsKeepsLegacyScalarWireAndReplacesDynamicMapsWithTypedList() throws Exception {
        UUID userId = UUID.randomUUID();
        UserFeedbackService.FeedbackStatistics legacy = new UserFeedbackService.FeedbackStatistics();
        legacy.setUserId(userId);
        legacy.setTotalFeedbacks(3L);
        legacy.setAverageRating(4.5);
        legacy.setFeedbackTypeCount(Map.of("quality", 2L, "自定义维度", 1L));
        legacy.setSentimentCount(Map.of("positive", 3L));

        UserFeedbackStatisticsQuery query = FeedbackStatisticsProjectionMapper.toQuery(
                legacy.getUserId(), legacy.getTotalFeedbacks(), legacy.getAverageRating(),
                legacy.getFeedbackTypeCount(), legacy.getSentimentCount());

        JsonNode json = jackson.readTree(jackson.writeValueAsString(query));
        Set<String> keys = new HashSet<>();
        json.fieldNames().forEachRemaining(keys::add);
        assertEquals(Set.of("userId", "totalFeedbacks", "averageRating", "feedbackTypeCount", "sentimentCount"),
                keys, "统计投影的顶层键集封闭");

        // 标量字段与旧 Service 统计对象序列化结果同值（键序无关）
        JsonNode legacyJson = jackson.readTree(jackson.writeValueAsString(legacy));
        assertEquals(legacyJson.get("userId"), json.get("userId"));
        assertEquals(legacyJson.get("totalFeedbacks"), json.get("totalFeedbacks"));
        assertEquals(legacyJson.get("averageRating"), json.get("averageRating"));

        // 动态 Map → 显式 {type,count} 列表，按分类键字典序；自定义分类原样保留
        assertTrue(json.get("feedbackTypeCount").isArray());
        assertEquals(2, json.get("feedbackTypeCount").size());
        assertEquals("quality", json.get("feedbackTypeCount").get(0).get("type").asText());
        assertEquals(2, json.get("feedbackTypeCount").get(0).get("count").asLong());
        assertEquals("自定义维度", json.get("feedbackTypeCount").get(1).get("type").asText());
        assertEquals(1, json.get("feedbackTypeCount").get(1).get("count").asLong());
        assertEquals(1, json.get("sentimentCount").size());
        assertEquals("positive", json.get("sentimentCount").get(0).get("type").asText());
        assertEquals(3, json.get("sentimentCount").get(0).get("count").asLong());
    }

    @Test
    void emptyStatisticsStayZeroDotZeroWithEmptyCategoryLists() throws Exception {
        UserFeedbackStatisticsQuery query = FeedbackStatisticsProjectionMapper.toQuery(
                UUID.randomUUID(), 0L, 0.0, Map.of(), Map.of());
        JsonNode json = jackson.readTree(jackson.writeValueAsString(query));
        assertEquals(0, json.get("totalFeedbacks").asLong());
        // 无数据时保留旧契约的 0.0（字段存在、非 null），不改为缺省或 null
        assertEquals("0.0", json.get("averageRating").asText());
        assertTrue(json.get("feedbackTypeCount").isArray());
        assertEquals(0, json.get("feedbackTypeCount").size());
        assertTrue(json.get("sentimentCount").isArray());
        assertEquals(0, json.get("sentimentCount").size());
    }

    @Test
    void globalStatisticsConvertsTypeCountsToSortedTypedList() throws Exception {
        UserFeedbackService.GlobalFeedbackStatistics legacy = new UserFeedbackService.GlobalFeedbackStatistics();
        legacy.setTotalFeedbacks(7L);
        legacy.setAverageRating(3.5);
        legacy.setFeedbackTypeCount(new HashMap<>(Map.of("relevance", 4L, "helpfulness", 3L)));

        JsonNode legacyJson = jackson.readTree(jackson.writeValueAsString(legacy));
        JsonNode json = jackson.readTree(jackson.writeValueAsString(FeedbackStatisticsProjectionMapper.toQuery(
                legacy.getTotalFeedbacks(), legacy.getAverageRating(), legacy.getFeedbackTypeCount())));

        Set<String> keys = new HashSet<>();
        json.fieldNames().forEachRemaining(keys::add);
        assertEquals(Set.of("totalFeedbacks", "averageRating", "feedbackTypeCount"), keys);
        assertEquals(legacyJson.get("totalFeedbacks"), json.get("totalFeedbacks"));
        assertEquals(legacyJson.get("averageRating"), json.get("averageRating"));
        assertEquals(2, json.get("feedbackTypeCount").size());
        assertEquals("helpfulness", json.get("feedbackTypeCount").get(0).get("type").asText());
        assertEquals(3, json.get("feedbackTypeCount").get(0).get("count").asLong());
        assertEquals("relevance", json.get("feedbackTypeCount").get(1).get("type").asText());
        assertEquals(4, json.get("feedbackTypeCount").get(1).get("count").asLong());
    }

    @Test
    void submissionReceiptKeepsTheExactLegacyWireShape() throws Exception {
        UUID feedbackId = UUID.randomUUID();
        Map<String, Object> legacyReceipt = new HashMap<>();
        legacyReceipt.put("message", "反馈已提交");
        legacyReceipt.put("feedbackId", feedbackId);
        assertEquals(jackson.readTree(jackson.writeValueAsString(legacyReceipt)),
                jackson.readTree(jackson.writeValueAsString(new FeedbackReceiptQuery("反馈已提交", feedbackId))),
                "回执投影必须与旧 Map 回执逐字段一致（键序无关）");
    }
}
