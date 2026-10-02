package com.kinlin.ai.controller;

import com.kinlin.ai.entity.Message;
import com.kinlin.ai.exception.GlobalExceptionHandler;
import com.kinlin.ai.service.ChatService;
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
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/** GET /chat/history stays path/status compatible and answers with message projection DTOs. */
@ExtendWith(MockitoExtension.class)
class ChatProjectionControllerTest {

    @Mock
    private ChatService chatService;

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
        mvc = MockMvcBuilders.standaloneSetup(new ChatController(chatService))
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
    void historyReturnsProjectionRowsInServiceOrder() throws Exception {
        String longContent = "长".repeat(500);
        Message user = message(Message.MessageRole.USER, "用户问题", null);
        Map<String, Object> metadata = new HashMap<>();
        metadata.put("confidence", 0.9);
        metadata.put("totalTokens", 120);
        metadata.put("thinkingEnabled", true);
        metadata.put("role_context", Map.of("system_prompt", "SECRET-PROMPT"));
        Message assistant = message(Message.MessageRole.ASSISTANT, longContent, metadata);
        when(chatService.getHistory("ctx_1", userId)).thenReturn(List.of(user, assistant));

        mvc.perform(get("/chat/history/{contextId}", "ctx_1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].role").value("USER"))
                .andExpect(jsonPath("$[0].content").value("用户问题"))
                .andExpect(jsonPath("$[0].metadata").doesNotExist())
                .andExpect(jsonPath("$[1].role").value("ASSISTANT"))
                .andExpect(jsonPath("$[1].content").value(longContent))
                .andExpect(jsonPath("$[1].metadata.totalTokens").value(120))
                .andExpect(jsonPath("$[1].metadata.confidence").value(0.9))
                .andExpect(jsonPath("$[1].metadata.thinkingEnabled").value(true))
                .andExpect(jsonPath("$[1].metadata.role_context").doesNotExist())
                .andExpect(jsonPath("$[1].createdAt").value("2026-09-30T08:30:15"));
    }

    @Test
    void historyForMissingOrForeignConversationStaysNotFound() throws Exception {
        when(chatService.getHistory(anyString(), org.mockito.ArgumentMatchers.eq(userId)))
                .thenThrow(new com.kinlin.ai.exception.ResourceNotFoundException("会话不存在或无权访问"));
        mvc.perform(get("/chat/history/{contextId}", "ctx_other"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.message").value("会话不存在或无权访问"));
    }

    @Test
    void historyWithoutAuthenticationKeepsTheRequireUserIdContract() throws Exception {
        SecurityContextHolder.clearContext();
        mvc.perform(get("/chat/history/{contextId}", "ctx_1"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.success").value(false));
        verifyNoInteractions(chatService);
    }

    private Message message(Message.MessageRole role, String content, Map<String, Object> metadata) {
        Message message = new Message();
        message.setId(UUID.randomUUID());
        message.setConversationId(UUID.randomUUID());
        message.setRole(role);
        message.setContent(content);
        message.setMessageType(Message.MessageType.TEXT);
        message.setMetadata(metadata);
        message.setCreatedAt(LocalDateTime.of(2026, 9, 30, 8, 30, 15));
        return message;
    }
}
