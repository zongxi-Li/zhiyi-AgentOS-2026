package com.kinlin.ai.controller;

import com.kinlin.ai.entity.UserFeedback;
import com.kinlin.ai.exception.GlobalExceptionHandler;
import com.kinlin.ai.service.UserFeedbackService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.MediaType;
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/** GET /api/feedback/user/{userId} answers with feedback projection DTOs, scoped to the authenticated user. */
@ExtendWith(MockitoExtension.class)
class FeedbackProjectionControllerTest {

    @Mock
    private UserFeedbackService feedbackService;

    private MockMvc mvc;
    private UUID userId;

    @BeforeEach
    void setUp() {
        userId = UUID.randomUUID();
        // 与 JacksonConfig 一致（JavaTimeModule + ISO 字符串）
        com.fasterxml.jackson.databind.ObjectMapper productionLikeMapper =
                new com.fasterxml.jackson.databind.ObjectMapper()
                        .registerModule(new com.fasterxml.jackson.datatype.jsr310.JavaTimeModule())
                        .disable(com.fasterxml.jackson.databind.SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);
        mvc = MockMvcBuilders.standaloneSetup(new UserFeedbackController(feedbackService))
                .setControllerAdvice(new GlobalExceptionHandler())
                .setMessageConverters(new MappingJackson2HttpMessageConverter(productionLikeMapper))
                .build();
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(userId, null, List.of()));
    }

    @AfterEach
    void clearIdentity() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void listAnswersProjectedRowsInServiceOrderForTheAuthenticatedUserOnly() throws Exception {
        UserFeedback feedback = feedback(true);
        UserFeedback minimal = feedback(false);
        when(feedbackService.getUserFeedbacks(eq(userId))).thenReturn(List.of(feedback, minimal));

        mvc.perform(get("/api/feedback/user/{userId}", userId))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(2))
                .andExpect(jsonPath("$[0].id").value(feedback.getId().toString()))
                .andExpect(jsonPath("$[0].userId").value(userId.toString()))
                .andExpect(jsonPath("$[0].conversationId").value(feedback.getConversationId().toString()))
                .andExpect(jsonPath("$[0].messageId").value(feedback.getMessageId().toString()))
                .andExpect(jsonPath("$[0].roleId").value(feedback.getRoleId().toString()))
                .andExpect(jsonPath("$[0].feedbackType").value("quality"))
                .andExpect(jsonPath("$[0].rating").value(5))
                .andExpect(jsonPath("$[0].content").value(feedback.getContent()))
                .andExpect(jsonPath("$[0].sentiment").value("positive"))
                .andExpect(jsonPath("$[0].createdAt").value("2026-10-01T09:00:00"))
                .andExpect(jsonPath("$[1].conversationId").isEmpty())
                .andExpect(jsonPath("$[1].rating").isEmpty())
                .andExpect(jsonPath("$[1].sentiment").isEmpty());
    }

    @Test
    void pathUserIdIsCompatibilityOnlyAndCannotSelectAnotherUsersRows() throws Exception {
        UserFeedback feedback = feedback(true);
        // 路径传他人 id：Service 实参仍是当前认证身份
        when(feedbackService.getUserFeedbacks(eq(userId))).thenReturn(List.of(feedback));

        mvc.perform(get("/api/feedback/user/{userId}", UUID.randomUUID()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(1))
                .andExpect(jsonPath("$[0].id").value(feedback.getId().toString()));
    }

    @Test
    void emptyListStaysAnEmptyJsonArray() throws Exception {
        when(feedbackService.getUserFeedbacks(eq(userId))).thenReturn(List.of());
        mvc.perform(get("/api/feedback/user/{userId}", userId))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(0));
    }

    @Test
    void withoutAuthenticationTheListStaysNotFound() throws Exception {
        SecurityContextHolder.clearContext();
        mvc.perform(get("/api/feedback/user/{userId}", userId))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.success").value(false));
        verifyNoInteractions(feedbackService);
    }

    @Test
    void statisticsAnswersSortedTypedCategoryListsForTheAuthenticatedUser() throws Exception {
        UserFeedbackService.FeedbackStatistics statistics = new UserFeedbackService.FeedbackStatistics();
        statistics.setUserId(userId);
        statistics.setTotalFeedbacks(2L);
        statistics.setAverageRating(4.0);
        statistics.setFeedbackTypeCount(Map.of("quality", 1L, "自定义维度", 1L));
        statistics.setSentimentCount(Map.of("positive", 2L));
        when(feedbackService.getFeedbackStatistics(eq(userId))).thenReturn(statistics);

        // 路径参数仅为兼容保留：传他人 id 时 Service 实参仍是当前认证身份
        mvc.perform(get("/api/feedback/user/{userId}/statistics", UUID.randomUUID()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.userId").value(userId.toString()))
                .andExpect(jsonPath("$.totalFeedbacks").value(2))
                .andExpect(jsonPath("$.averageRating").value(4.0))
                .andExpect(jsonPath("$.feedbackTypeCount.length()").value(2))
                .andExpect(jsonPath("$.feedbackTypeCount[0].type").value("quality"))
                .andExpect(jsonPath("$.feedbackTypeCount[0].count").value(1))
                .andExpect(jsonPath("$.feedbackTypeCount[1].type").value("自定义维度"))
                .andExpect(jsonPath("$.feedbackTypeCount[1].count").value(1))
                .andExpect(jsonPath("$.sentimentCount.length()").value(1))
                .andExpect(jsonPath("$.sentimentCount[0].type").value("positive"))
                .andExpect(jsonPath("$.sentimentCount[0].count").value(2));
    }

    @Test
    void emptyUserStatisticsKeepZeroDefaultsAndEmptyCategoryLists() throws Exception {
        UserFeedbackService.FeedbackStatistics statistics = new UserFeedbackService.FeedbackStatistics();
        statistics.setUserId(userId);
        statistics.setTotalFeedbacks(0L);
        statistics.setAverageRating(0.0);
        statistics.setFeedbackTypeCount(Map.of());
        statistics.setSentimentCount(Map.of());
        when(feedbackService.getFeedbackStatistics(eq(userId))).thenReturn(statistics);

        mvc.perform(get("/api/feedback/user/{userId}/statistics", userId))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.totalFeedbacks").value(0))
                .andExpect(jsonPath("$.averageRating").value(0.0))
                .andExpect(jsonPath("$.feedbackTypeCount.length()").value(0))
                .andExpect(jsonPath("$.sentimentCount.length()").value(0));
    }

    @Test
    void globalStatisticsAnswersTypedCategoryList() throws Exception {
        UserFeedbackService.GlobalFeedbackStatistics statistics = new UserFeedbackService.GlobalFeedbackStatistics();
        statistics.setTotalFeedbacks(7L);
        statistics.setAverageRating(3.5);
        statistics.setFeedbackTypeCount(Map.of("relevance", 4L, "helpfulness", 3L));
        when(feedbackService.getGlobalStatistics()).thenReturn(statistics);

        mvc.perform(get("/api/feedback/statistics"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.totalFeedbacks").value(7))
                .andExpect(jsonPath("$.averageRating").value(3.5))
                .andExpect(jsonPath("$.feedbackTypeCount.length()").value(2))
                .andExpect(jsonPath("$.feedbackTypeCount[0].type").value("helpfulness"))
                .andExpect(jsonPath("$.feedbackTypeCount[0].count").value(3))
                .andExpect(jsonPath("$.feedbackTypeCount[1].type").value("relevance"))
                .andExpect(jsonPath("$.feedbackTypeCount[1].count").value(4));
    }

    @Test
    void submissionReceiptKeepsLegacyMessageIdAndStatus() throws Exception {
        UserFeedback saved = new UserFeedback();
        saved.setId(UUID.randomUUID());
        when(feedbackService.createFeedback(eq(userId), eq(null), eq(null), eq(null),
                eq("quality"), eq(5), eq("很满意，长文本不截断"))).thenReturn(saved);

        mvc.perform(post("/api/feedback")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"userId":"%s","feedbackType":"quality","rating":5,"content":"很满意，长文本不截断"}
                                """.formatted(userId)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.message").value("反馈已提交"))
                .andExpect(jsonPath("$.feedbackId").value(saved.getId().toString()));
    }

    private UserFeedback feedback(boolean fullyPopulated) {
        UserFeedback feedback = new UserFeedback();
        feedback.setId(UUID.randomUUID());
        feedback.setUserId(userId);
        if (fullyPopulated) {
            feedback.setConversationId(UUID.randomUUID());
            feedback.setMessageId(UUID.randomUUID());
            feedback.setRoleId(UUID.randomUUID());
            feedback.setRating(5);
            feedback.setSentiment("positive");
        }
        feedback.setFeedbackType("quality");
        feedback.setContent("长反馈正文不截断：" + "细".repeat(400));
        feedback.setCreatedAt(LocalDateTime.of(2026, 10, 1, 9, 0, 0));
        return feedback;
    }
}
