package com.kinlin.ai.controller;

import com.kinlin.ai.entity.Conversation;
import com.kinlin.ai.exception.GlobalExceptionHandler;
import com.kinlin.ai.projection.conversation.dto.ConversationQuery;
import com.kinlin.ai.service.ConversationService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.MediaType;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/** Conversation query endpoints stay path/status compatible and now answer with projection DTOs. */
@ExtendWith(MockitoExtension.class)
class ConversationProjectionControllerTest {

    @Mock
    private ConversationService conversationService;

    private MockMvc mvc;
    private UUID userId;
    private Conversation owned;

    @BeforeEach
    void setUp() {
        userId = UUID.randomUUID();
        // 与 JacksonConfig 一致（JavaTimeModule + ISO 字符串），standalone 默认转换器否则输出时间数组
        com.fasterxml.jackson.databind.ObjectMapper productionLikeMapper = new com.fasterxml.jackson.databind.ObjectMapper()
                .registerModule(new com.fasterxml.jackson.datatype.jsr310.JavaTimeModule())
                .disable(com.fasterxml.jackson.databind.SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);
        mvc = MockMvcBuilders.standaloneSetup(new ConversationController(conversationService))
                .setControllerAdvice(new GlobalExceptionHandler())
                .setMessageConverters(new org.springframework.http.converter.json.MappingJackson2HttpMessageConverter(productionLikeMapper))
                .build();
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(userId, null, List.of()));
        owned = new Conversation();
        owned.setId(UUID.randomUUID());
        owned.setUserId(userId);
        owned.setRoleId(UUID.randomUUID());
        owned.setContextId("ctx_owned");
        owned.setTitle("既有标题");
        owned.setWorkspaceMode("chat");
        owned.setPreview("列表预览");
        owned.setCreatedAt(LocalDateTime.of(2026, 9, 30, 8, 30, 15));
        owned.setUpdatedAt(LocalDateTime.of(2026, 10, 1, 9, 0, 0));
    }

    @AfterEach
    void clearIdentity() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void conversationListReturnsProjectionRowsWithTheLegacyFieldSet() throws Exception {
        when(conversationService.getUserConversations(userId)).thenReturn(List.of(owned));
        mvc.perform(get("/conversations"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].id").value(owned.getId().toString()))
                .andExpect(jsonPath("$[0].userId").value(userId.toString()))
                .andExpect(jsonPath("$[0].roleId").value(owned.getRoleId().toString()))
                .andExpect(jsonPath("$[0].contextId").value("ctx_owned"))
                .andExpect(jsonPath("$[0].title").value("既有标题"))
                .andExpect(jsonPath("$[0].workspaceMode").value("chat"))
                .andExpect(jsonPath("$[0].preview").value("列表预览"))
                .andExpect(jsonPath("$[0].createdAt").value("2026-09-30T08:30:15"))
                .andExpect(jsonPath("$[0].updatedAt").value("2026-10-01T09:00:00"));
        assertInstanceOf(ConversationQuery.class,
                new ConversationController(conversationService).getUserConversations(null).getBody().get(0));
    }

    @Test
    void workspaceModeFilterKeepsReachingTheService() throws Exception {
        when(conversationService.getUserConversations(userId, "agent")).thenReturn(List.of());
        mvc.perform(get("/conversations").param("workspaceMode", "agent"))
                .andExpect(status().isOk())
                .andExpect(content().json("[]"));
        verify(conversationService).getUserConversations(userId, "agent");
        verify(conversationService, never()).getUserConversations(any(UUID.class));
    }

    @Test
    void listWithoutAuthenticationStaysRejected() throws Exception {
        SecurityContextHolder.clearContext();
        mvc.perform(get("/conversations")).andExpect(status().isBadRequest());
        verifyNoInteractions(conversationService);
    }

    @Test
    void contextLookupProjectsOnlyForTheOwner() throws Exception {
        when(conversationService.getConversationByContextIdForUser("ctx_owned", userId))
                .thenReturn(Optional.of(owned));
        mvc.perform(get("/conversations/{contextId}", "ctx_owned"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.contextId").value("ctx_owned"))
                .andExpect(jsonPath("$.title").value("既有标题"));

        when(conversationService.getConversationByContextIdForUser("ctx_other", userId))
                .thenReturn(Optional.empty());
        mvc.perform(get("/conversations/{contextId}", "ctx_other"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.message").value("会话不存在或无权访问"));
    }

    @Test
    void titleUpdateProjectsTheServiceResultWithoutTouchingCommandHandling() throws Exception {
        Conversation renamed = new Conversation();
        renamed.setId(owned.getId());
        renamed.setUserId(userId);
        renamed.setContextId("ctx_owned");
        renamed.setTitle("新标题");
        when(conversationService.updateTitle(owned.getId(), userId, "新标题")).thenReturn(renamed);

        mvc.perform(put("/conversations/{id}/title", owned.getId())
                        .contentType(MediaType.APPLICATION_JSON).content("{\"title\":\"新标题\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.title").value("新标题"))
                .andExpect(jsonPath("$.id").value(owned.getId().toString()));
        verify(conversationService).updateTitle(owned.getId(), userId, "新标题");
    }

    @Test
    void detailKeepsAutoTitleAndPreviewBehaviorAndProjectsBoth() throws Exception {
        when(conversationService.getConversationByIdForUser(owned.getId(), userId))
                .thenReturn(Optional.of(owned));
        when(conversationService.getPreviewContent(owned.getId())).thenReturn("首条用户消息");

        mvc.perform(get("/conversations/{id}/detail", owned.getId()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.conversation.id").value(owned.getId().toString()))
                .andExpect(jsonPath("$.conversation.title").value("既有标题"))
                .andExpect(jsonPath("$.preview").value("首条用户消息"));
        verify(conversationService, never()).autoGenerateTitle(any(UUID.class));
    }

    @Test
    void detailStillAutoGeneratesTitleOnlyWhenTitleIsMissing() throws Exception {
        Conversation untitled = new Conversation();
        untitled.setId(owned.getId());
        untitled.setUserId(userId);
        untitled.setContextId("ctx_owned");
        untitled.setWorkspaceMode("chat");
        when(conversationService.getConversationByIdForUser(owned.getId(), userId))
                .thenReturn(Optional.of(untitled));
        Conversation generated = new Conversation();
        generated.setId(owned.getId());
        generated.setUserId(userId);
        generated.setContextId("ctx_owned");
        generated.setTitle("自动生成标题");
        when(conversationService.autoGenerateTitle(owned.getId())).thenReturn(generated);
        when(conversationService.getPreviewContent(owned.getId())).thenReturn("预览");

        mvc.perform(get("/conversations/{id}/detail", owned.getId()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.conversation.title").value("自动生成标题"))
                .andExpect(jsonPath("$.preview").value("预览"));
        verify(conversationService).autoGenerateTitle(owned.getId());
        verify(conversationService).getPreviewContent(owned.getId());
    }

    @Test
    void detailForMissingOrForeignConversationStaysNotFound() throws Exception {
        when(conversationService.getConversationByIdForUser(any(UUID.class), eq(userId)))
                .thenReturn(Optional.empty());
        UUID id = UUID.randomUUID();
        mvc.perform(get("/conversations/{id}/detail", id))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.success").value(false));
    }

    @Test
    void queryEndpointsWithoutAuthenticationKeepTheRequireUserIdContract() throws Exception {
        SecurityContextHolder.clearContext();
        UUID id = UUID.randomUUID();
        mvc.perform(get("/conversations/{id}/detail", id)).andExpect(status().isNotFound());
        mvc.perform(put("/conversations/{id}/title", id).contentType(MediaType.APPLICATION_JSON)
                        .content("{\"title\":\"x\"}"))
                .andExpect(status().isNotFound());
        verifyNoInteractions(conversationService);
    }
}
