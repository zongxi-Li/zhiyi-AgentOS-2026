package com.kinlin.ai.service;

import com.kinlin.ai.client.AiChatClient;
import com.kinlin.ai.client.PlatformAiClientException;
import com.kinlin.ai.dto.ChatRequest;
import com.kinlin.ai.dto.ChatResponse;
import com.kinlin.ai.entity.Conversation;
import com.kinlin.ai.entity.Message;
import com.kinlin.ai.exception.ResourceNotFoundException;
import com.kinlin.ai.repository.ConversationRepository;
import com.kinlin.ai.repository.MessageRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.Spy;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.quality.Strictness;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import java.util.*;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/**
 * ChatService单元测试
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class ChatServiceTest {

    @Mock
    private ConversationRepository conversationRepository;

    @Mock
    private MessageRepository messageRepository;

    @Mock
    private AiChatClient aiChatClient;

    @Spy
    private TransactionTemplate transactionTemplate =
            new TransactionTemplate(mock(PlatformTransactionManager.class));

    @InjectMocks
    private ChatService chatService;

    private ChatRequest chatRequest;
    private UUID userId;
    private UUID roleId;

    @BeforeEach
    void setUp() {
        userId = UUID.randomUUID();
        roleId = UUID.randomUUID();

        chatRequest = new ChatRequest();
        chatRequest.setText("测试消息");
        chatRequest.setRoleId(roleId);
    }

    @Test
    void testSendMessage_NewConversation() {
        // Given
        Conversation conversation = new Conversation();
        conversation.setId(UUID.randomUUID());
        conversation.setContextId(UUID.randomUUID().toString());
        conversation.setUserId(userId);
        conversation.setRoleId(roleId);

        ChatResponse aiResponse = new ChatResponse();
        aiResponse.setText("AI回复");
        aiResponse.setConfidence(0.95);

        when(conversationRepository.findByContextId(anyString())).thenReturn(Optional.empty());
        when(conversationRepository.save(any(Conversation.class))).thenReturn(conversation);
        when(messageRepository.findByConversationIdOrderByCreatedAtAsc(any(UUID.class)))
                .thenReturn(Collections.emptyList());
        when(aiChatClient.sendText(any(AiChatClient.AiChatCommand.class)))
                .thenReturn(aiResponse);

        // When
        ChatResponse response = chatService.sendMessage(chatRequest, userId);

        // Then
        assertNotNull(response);
        assertEquals("AI回复", response.getText());
        assertEquals(conversation.getContextId(), response.getContextId());
        verify(messageRepository, times(2)).save(any(Message.class));
    }

    @Test
    void testSendMessage_ExistingConversation() {
        // Given
        String contextId = UUID.randomUUID().toString();
        chatRequest.setContextId(contextId);

        Conversation conversation = new Conversation();
        conversation.setId(UUID.randomUUID());
        conversation.setContextId(contextId);
        conversation.setUserId(userId);

        ChatResponse aiResponse = new ChatResponse();
        aiResponse.setText("AI回复");

        when(conversationRepository.findByContextId(contextId))
                .thenReturn(Optional.of(conversation));
        when(messageRepository.findByConversationIdOrderByCreatedAtAsc(any(UUID.class)))
                .thenReturn(Collections.emptyList());
        when(aiChatClient.sendText(any(AiChatClient.AiChatCommand.class)))
                .thenReturn(aiResponse);

        // When
        ChatResponse response = chatService.sendMessage(chatRequest, userId);

        // Then
        assertNotNull(response);
        verify(conversationRepository, never()).save(any(Conversation.class));
    }

    @Test
    void testSendMessage_DoesNotReuseConversationFromAnotherWorkspace() {
        String chatContextId = UUID.randomUUID().toString();
        chatRequest.setContextId(chatContextId);
        chatRequest.setWorkspaceMode("agent");

        Conversation chatConversation = new Conversation();
        chatConversation.setId(UUID.randomUUID());
        chatConversation.setContextId(chatContextId);
        chatConversation.setWorkspaceMode("chat");

        ChatResponse aiResponse = new ChatResponse();
        aiResponse.setText("Agent reply");

        when(conversationRepository.findByContextId(chatContextId)).thenReturn(Optional.of(chatConversation));
        when(conversationRepository.save(any(Conversation.class))).thenAnswer(invocation -> {
            Conversation saved = invocation.getArgument(0);
            saved.setId(UUID.randomUUID());
            return saved;
        });
        when(messageRepository.findByConversationIdOrderByCreatedAtAsc(any(UUID.class)))
                .thenReturn(Collections.emptyList());
        when(aiChatClient.sendText(any(AiChatClient.AiChatCommand.class)))
                .thenReturn(aiResponse);

        ChatResponse response = chatService.sendMessage(chatRequest, userId);

        var captor = org.mockito.ArgumentCaptor.forClass(Conversation.class);
        verify(conversationRepository).save(captor.capture());
        assertEquals("agent", captor.getValue().getWorkspaceMode());
        assertNotEquals(chatContextId, captor.getValue().getContextId());
        assertEquals(captor.getValue().getContextId(), response.getContextId());
    }

    @Test
    void testSendMessage_DoesNotReuseConversationOwnedByAnotherUser() {
        String contextId = UUID.randomUUID().toString();
        chatRequest.setContextId(contextId);
        chatRequest.setWorkspaceMode("chat");

        Conversation anotherUsersConversation = new Conversation();
        anotherUsersConversation.setId(UUID.randomUUID());
        anotherUsersConversation.setContextId(contextId);
        anotherUsersConversation.setUserId(UUID.randomUUID());
        anotherUsersConversation.setWorkspaceMode("chat");

        ChatResponse aiResponse = new ChatResponse();
        aiResponse.setText("Fresh reply");

        when(conversationRepository.findByContextId(contextId))
                .thenReturn(Optional.of(anotherUsersConversation));
        when(conversationRepository.save(any(Conversation.class))).thenAnswer(invocation -> {
            Conversation saved = invocation.getArgument(0);
            saved.setId(UUID.randomUUID());
            return saved;
        });
        when(messageRepository.findByConversationIdOrderByCreatedAtAsc(any(UUID.class)))
                .thenReturn(Collections.emptyList());
        when(aiChatClient.sendText(any(AiChatClient.AiChatCommand.class)))
                .thenReturn(aiResponse);

        chatService.sendMessage(chatRequest, userId);

        var captor = org.mockito.ArgumentCaptor.forClass(Conversation.class);
        verify(conversationRepository).save(captor.capture());
        assertEquals(userId, captor.getValue().getUserId());
        assertNotEquals(contextId, captor.getValue().getContextId());
    }

    @Test
    void testGetHistory() {
        // Given
        String contextId = UUID.randomUUID().toString();
        Conversation conversation = new Conversation();
        conversation.setId(UUID.randomUUID());

        Message message = new Message();
        message.setContent("测试消息");

        when(conversationRepository.findByContextIdAndUserId(contextId, userId))
                .thenReturn(Optional.of(conversation));
        when(messageRepository.findByConversationIdOrderByCreatedAtAsc(conversation.getId()))
                .thenReturn(List.of(message));

        // When
        List<Message> history = chatService.getHistory(contextId, userId);

        // Then
        assertNotNull(history);
        assertEquals(1, history.size());
        assertEquals("测试消息", history.get(0).getContent());
    }

    @Test
    void testClearHistory() {
        // Given
        String contextId = UUID.randomUUID().toString();
        Conversation conversation = new Conversation();
        conversation.setId(UUID.randomUUID());

        Message message = new Message();
        message.setContent("测试消息");

        when(conversationRepository.findByContextIdAndUserId(contextId, userId))
                .thenReturn(Optional.of(conversation));
        when(messageRepository.findByConversationIdOrderByCreatedAtAsc(conversation.getId()))
                .thenReturn(List.of(message));

        // When
        chatService.clearHistory(contextId, userId);

        // Then
        verify(messageRepository).deleteAll(anyList());
        verify(conversationRepository).delete(conversation);
    }

    @Test
    void testSendMessage_EmptyText() {
        // Given
        chatRequest.setText("");
        Conversation conversation = new Conversation();
        conversation.setId(UUID.randomUUID());
        conversation.setContextId(UUID.randomUUID().toString());

        ChatResponse aiResponse = new ChatResponse();
        aiResponse.setText("AI回复");

        when(conversationRepository.findByContextId(anyString())).thenReturn(Optional.empty());
        when(conversationRepository.save(any(Conversation.class))).thenReturn(conversation);
        when(messageRepository.findByConversationIdOrderByCreatedAtAsc(any(UUID.class)))
                .thenReturn(Collections.emptyList());
        when(aiChatClient.sendText(any(AiChatClient.AiChatCommand.class)))
                .thenReturn(aiResponse);

        // When
        ChatResponse response = chatService.sendMessage(chatRequest, userId);

        // Then
        assertNotNull(response);
        var commandCaptor = org.mockito.ArgumentCaptor.forClass(AiChatClient.AiChatCommand.class);
        verify(aiChatClient).sendText(commandCaptor.capture());
        assertEquals("", commandCaptor.getValue().text());
    }

    @Test
    void testSendMessage_VeryLongText() {
        // Given
        String longText = "测试".repeat(1000); // 2000字符
        chatRequest.setText(longText);
        Conversation conversation = new Conversation();
        conversation.setId(UUID.randomUUID());
        conversation.setContextId(UUID.randomUUID().toString());

        ChatResponse aiResponse = new ChatResponse();
        aiResponse.setText("AI回复");

        when(conversationRepository.findByContextId(anyString())).thenReturn(Optional.empty());
        when(conversationRepository.save(any(Conversation.class))).thenReturn(conversation);
        when(messageRepository.findByConversationIdOrderByCreatedAtAsc(any(UUID.class)))
                .thenReturn(Collections.emptyList());
        when(aiChatClient.sendText(any(AiChatClient.AiChatCommand.class)))
                .thenReturn(aiResponse);

        // When
        ChatResponse response = chatService.sendMessage(chatRequest, userId);

        // Then
        assertNotNull(response);
        var commandCaptor = org.mockito.ArgumentCaptor.forClass(AiChatClient.AiChatCommand.class);
        verify(aiChatClient).sendText(commandCaptor.capture());
        assertEquals(longText, commandCaptor.getValue().text());
    }

    @Test
    void testSendMessage_SpecialCharacters() {
        // Given
        chatRequest.setText("测试特殊字符：!@#$%^&*()_+-=[]{}|;':\",./<>?");
        Conversation conversation = new Conversation();
        conversation.setId(UUID.randomUUID());
        conversation.setContextId(UUID.randomUUID().toString());

        ChatResponse aiResponse = new ChatResponse();
        aiResponse.setText("AI回复");

        when(conversationRepository.findByContextId(anyString())).thenReturn(Optional.empty());
        when(conversationRepository.save(any(Conversation.class))).thenReturn(conversation);
        when(messageRepository.findByConversationIdOrderByCreatedAtAsc(any(UUID.class)))
                .thenReturn(Collections.emptyList());
        when(aiChatClient.sendText(any(AiChatClient.AiChatCommand.class)))
                .thenReturn(aiResponse);

        // When
        ChatResponse response = chatService.sendMessage(chatRequest, userId);

        // Then
        assertNotNull(response);
    }

    @Test
    void testGetHistory_EmptyHistory() {
        // Given
        String contextId = UUID.randomUUID().toString();
        Conversation conversation = new Conversation();
        conversation.setId(UUID.randomUUID());

        when(conversationRepository.findByContextIdAndUserId(contextId, userId))
                .thenReturn(Optional.of(conversation));
        when(messageRepository.findByConversationIdOrderByCreatedAtAsc(conversation.getId()))
                .thenReturn(Collections.emptyList());

        // When
        List<Message> history = chatService.getHistory(contextId, userId);

        // Then
        assertNotNull(history);
        assertTrue(history.isEmpty());
    }

    @Test
    void testGetHistory_ConversationNotFound() {
        // Given
        String contextId = UUID.randomUUID().toString();

        when(conversationRepository.findByContextIdAndUserId(contextId, userId))
                .thenReturn(Optional.empty());

        // When & Then：会话不存在或非本人时应抛 404 语义异常
        assertThrows(ResourceNotFoundException.class,
                () -> chatService.getHistory(contextId, userId));
    }

    @Test
    void testSendMessage_WithHistory() {
        // Given
        String contextId = UUID.randomUUID().toString();
        chatRequest.setContextId(contextId);

        Conversation conversation = new Conversation();
        conversation.setId(UUID.randomUUID());
        conversation.setContextId(contextId);
        conversation.setUserId(userId);

        Message previousMessage = new Message();
        previousMessage.setContent("之前的消息");
        previousMessage.setRole(Message.MessageRole.USER);

        ChatResponse aiResponse = new ChatResponse();
        aiResponse.setText("AI回复");

        when(conversationRepository.findByContextId(contextId))
                .thenReturn(Optional.of(conversation));
        when(messageRepository.findByConversationIdOrderByCreatedAtAsc(conversation.getId()))
                .thenReturn(List.of(previousMessage));
        when(aiChatClient.sendText(any(AiChatClient.AiChatCommand.class)))
                .thenReturn(aiResponse);

        // When
        ChatResponse response = chatService.sendMessage(chatRequest, userId);

        // Then
        assertNotNull(response);
        var commandCaptor = org.mockito.ArgumentCaptor.forClass(AiChatClient.AiChatCommand.class);
        verify(aiChatClient).sendText(commandCaptor.capture());
        assertTrue(commandCaptor.getValue().context().size() > 0);
    }

    @Test
    void testSendMessage_WithRuntimeModelSettings() {
        Conversation conversation = new Conversation();
        conversation.setId(UUID.randomUUID());
        conversation.setContextId(UUID.randomUUID().toString());

        chatRequest.setModel("qwen3-plus");
        chatRequest.setBaseUrl("https://example.com/v1");
        chatRequest.setApiKey("test-key");
        chatRequest.setReasoningEffort("high");
        chatRequest.setToolMode("auto");

        ChatResponse aiResponse = new ChatResponse();
        aiResponse.setText("指定模型回复");

        when(conversationRepository.save(any(Conversation.class))).thenReturn(conversation);
        when(messageRepository.findByConversationIdOrderByCreatedAtAsc(any(UUID.class)))
                .thenReturn(Collections.emptyList());
        when(aiChatClient.sendText(any(AiChatClient.AiChatCommand.class)))
                .thenReturn(aiResponse);

        ChatResponse response = chatService.sendMessage(chatRequest, userId);

        assertEquals("指定模型回复", response.getText());
        var commandCaptor = org.mockito.ArgumentCaptor.forClass(AiChatClient.AiChatCommand.class);
        verify(aiChatClient).sendText(commandCaptor.capture());
        AiChatClient.AiChatCommand command = commandCaptor.getValue();
        assertEquals("qwen3-plus", command.model());
        assertEquals("https://example.com/v1", command.baseUrl());
        assertEquals("test-key", command.apiKey());
        assertEquals("high", command.thinkingMode());
        assertEquals("auto", command.toolMode());
    }

    @Test
    void testSendMessage_TransportFailureKeepsFrozenFallbackResponse() {
        // Given：表征冻结（J1.2 §25-B）——Python 不可用时用户可见 fallback 不变
        when(conversationRepository.findByContextId(anyString())).thenReturn(Optional.empty());
        when(conversationRepository.save(any(Conversation.class))).thenAnswer(invocation -> {
            Conversation conv = invocation.getArgument(0);
            conv.setId(UUID.randomUUID());
            return conv;
        });
        when(messageRepository.findByConversationIdOrderByCreatedAtAsc(any(UUID.class)))
                .thenReturn(Collections.emptyList());
        when(aiChatClient.sendText(any(AiChatClient.AiChatCommand.class)))
                .thenThrow(new PlatformAiClientException(
                        PlatformAiClientException.Type.TIMEOUT, "Did not observe any item"));

        // When
        ChatResponse response = chatService.sendMessage(chatRequest, userId);

        // Then
        assertEquals("抱歉，AI服务当前不可用，请稍后重试。", response.getText());
        assertEquals(0.0, response.getConfidence());
        verify(messageRepository, times(2)).save(any(Message.class));
    }
}

