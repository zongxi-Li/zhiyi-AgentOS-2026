package com.kinlin.ai.controller;

import com.kinlin.ai.entity.Message;
import com.kinlin.ai.exception.GlobalExceptionHandler;
import com.kinlin.ai.service.ChatService;
import com.kinlin.ai.service.SearchService;
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

import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/** GET /search/messages and /search/all-messages answer with message projection DTOs. */
@ExtendWith(MockitoExtension.class)
class SearchProjectionControllerTest {

    private static final String KEYWORD = "GLM";
    private static final String PROMPT_SENTINEL = "SECRET-SYSTEM-PROMPT";

    @Mock
    private ChatService chatService;

    @Mock
    private SearchService searchService;

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
        mvc = MockMvcBuilders.standaloneSetup(new SearchController(chatService, searchService))
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
    void inConversationSearchMatchesCaseInsensitivelyInServiceOrderAndCannotBeReidentifiedByHeader() throws Exception {
        Map<String, Object> metadata = new HashMap<>();
        metadata.put("totalTokens", 1049);
        metadata.put("effectiveModel", "glm-5.3-flash");
        metadata.put("role_context", Map.of("system_prompt", PROMPT_SENTINEL));
        Message miss = message(Message.MessageRole.USER, "今天天气如何", null);
        Message firstHit = message(Message.MessageRole.ASSISTANT, "本轮由 GLM 模型生成", metadata);
        Message secondHit = message(Message.MessageRole.USER, "再解释下 glm 的用法", null);
        when(chatService.getHistory("ctx_1", userId)).thenReturn(List.of(miss, firstHit, secondHit));

        mvc.perform(get("/search/messages")
                        .param("keyword", KEYWORD)
                        .param("contextId", "ctx_1")
                        // X-User-Id 已被 SensitiveIdentityHeaderFilter 剥离，身份只认安全上下文
                        .header("X-User-Id", UUID.randomUUID().toString()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(2))
                .andExpect(jsonPath("$[0].role").value("ASSISTANT"))
                .andExpect(jsonPath("$[0].content").value("本轮由 GLM 模型生成"))
                .andExpect(jsonPath("$[0].metadata.totalTokens").value(1049))
                .andExpect(jsonPath("$[0].metadata.effectiveModel").value("glm-5.3-flash"))
                .andExpect(jsonPath("$[0].metadata.role_context").doesNotExist())
                .andExpect(jsonPath("$[0].createdAt").value("2026-10-01T09:00:00"))
                .andExpect(jsonPath("$[1].role").value("USER"))
                .andExpect(jsonPath("$[1].metadata").doesNotExist());

        verify(chatService).getHistory(eq("ctx_1"), eq(userId));
    }

    @Test
    void missingOrEmptyContextIdAnswersEmptyListWithoutTouchingSearch() throws Exception {
        mvc.perform(get("/search/messages").param("keyword", KEYWORD))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(0));
        mvc.perform(get("/search/messages").param("keyword", KEYWORD).param("contextId", ""))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(0));
        verifyNoInteractions(chatService, searchService);
    }

    @Test
    void inConversationSearchForForeignConversationStaysNotFound() throws Exception {
        when(chatService.getHistory("ctx_other", userId))
                .thenThrow(new com.kinlin.ai.exception.ResourceNotFoundException("会话不存在或无权访问"));
        mvc.perform(get("/search/messages").param("keyword", KEYWORD).param("contextId", "ctx_other"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.success").value(false));
    }

    @Test
    void crossConversationSearchPassesCurrentIdentityAndKeywordAndProjectsResults() throws Exception {
        Map<String, Object> metadata = new HashMap<>();
        metadata.put("totalTokens", 30);
        metadata.put("sources", List.of("internal://secret"));
        Message hit = message(Message.MessageRole.ASSISTANT, "跨会话命中的 GLM 回答", metadata);
        when(searchService.searchMessages(userId, KEYWORD)).thenReturn(List.of(hit));

        mvc.perform(get("/search/all-messages")
                        .param("keyword", KEYWORD)
                        .header("X-User-Id", UUID.randomUUID().toString()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(1))
                .andExpect(jsonPath("$[0].content").value("跨会话命中的 GLM 回答"))
                .andExpect(jsonPath("$[0].metadata.totalTokens").value(30))
                .andExpect(jsonPath("$[0].metadata.sources").doesNotExist());

        verify(searchService).searchMessages(eq(userId), eq(KEYWORD));
    }

    @Test
    void bothSearchRoutesStayUnauthenticatedBadRequest() throws Exception {
        SecurityContextHolder.clearContext();
        mvc.perform(get("/search/messages").param("keyword", KEYWORD).param("contextId", "ctx_1"))
                .andExpect(status().isBadRequest());
        mvc.perform(get("/search/all-messages").param("keyword", KEYWORD))
                .andExpect(status().isBadRequest());
        verifyNoInteractions(chatService, searchService);
    }

    private Message message(Message.MessageRole role, String content, Map<String, Object> metadata) {
        Message message = new Message();
        message.setId(UUID.randomUUID());
        message.setConversationId(UUID.randomUUID());
        message.setRole(role);
        message.setContent(content);
        message.setMessageType(Message.MessageType.TEXT);
        message.setMetadata(metadata);
        message.setCreatedAt(LocalDateTime.of(2026, 10, 1, 9, 0, 0));
        return message;
    }
}
