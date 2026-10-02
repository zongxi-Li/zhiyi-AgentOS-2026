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
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.time.LocalDateTime;
import java.util.List;
import java.util.UUID;

import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
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
