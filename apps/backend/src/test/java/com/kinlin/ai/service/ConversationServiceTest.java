package com.kinlin.ai.service;

import com.kinlin.ai.entity.Conversation;
import com.kinlin.ai.entity.Message;
import com.kinlin.ai.repository.ConversationRepository;
import com.kinlin.ai.repository.MessageRepository;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InOrder;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.Optional;
import java.util.List;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class ConversationServiceTest {

    @Mock
    private ConversationRepository conversationRepository;

    @Mock
    private MessageRepository messageRepository;

    @InjectMocks
    private ConversationService conversationService;

    @Test
    void deleteConversationRemovesOwnedMessagesBeforeConversation() {
        UUID userId = UUID.randomUUID();
        UUID conversationId = UUID.randomUUID();
        Conversation conversation = conversation(conversationId, userId);
        when(conversationRepository.findById(conversationId)).thenReturn(Optional.of(conversation));

        assertTrue(conversationService.deleteConversation(conversationId, userId));

        InOrder deletionOrder = inOrder(messageRepository, conversationRepository);
        deletionOrder.verify(messageRepository).deleteByConversationId(conversationId);
        deletionOrder.verify(conversationRepository).delete(conversation);
    }

    @Test
    void deleteConversationRejectsAnotherUsersConversation() {
        UUID ownerId = UUID.randomUUID();
        UUID requesterId = UUID.randomUUID();
        UUID conversationId = UUID.randomUUID();
        Conversation conversation = conversation(conversationId, ownerId);
        when(conversationRepository.findById(conversationId)).thenReturn(Optional.of(conversation));

        assertFalse(conversationService.deleteConversation(conversationId, requesterId));

        verify(messageRepository, never()).deleteByConversationId(conversationId);
        verify(conversationRepository, never()).delete(conversation);
    }

    @Test
    void deleteConversationReturnsFalseWhenConversationDoesNotExist() {
        UUID conversationId = UUID.randomUUID();
        when(conversationRepository.findById(conversationId)).thenReturn(Optional.empty());

        assertFalse(conversationService.deleteConversation(conversationId, UUID.randomUUID()));

        verify(messageRepository, never()).deleteByConversationId(conversationId);
    }

    @Test
    void listsOnlyTheRequestedWorkspace() {
        UUID userId = UUID.randomUUID();
        when(conversationRepository.findRecentConversationsByUserIdAndWorkspaceMode(userId, "agent"))
                .thenReturn(List.of());

        conversationService.getUserConversations(userId, "agent");

        verify(conversationRepository).findRecentConversationsByUserIdAndWorkspaceMode(userId, "agent");
        verify(conversationRepository, never()).findRecentConversationsByUserId(userId);
    }

    @Test
    void hydratesConversationPreviewsWithBulkMessageQueries() {
        UUID userId = UUID.randomUUID();
        UUID firstId = UUID.randomUUID();
        UUID secondId = UUID.randomUUID();
        Conversation first = conversation(firstId, userId);
        Conversation second = conversation(secondId, userId);
        second.setTitle("已有标题");
        when(conversationRepository.findRecentConversationsByUserIdAndWorkspaceMode(userId, "chat"))
                .thenReturn(List.of(first, second));

        MessageRepository.ConversationMessagePreview firstPreview =
                org.mockito.Mockito.mock(MessageRepository.ConversationMessagePreview.class);
        when(firstPreview.getConversationId()).thenReturn(firstId);
        when(firstPreview.getContent()).thenReturn("第一条用户消息");
        when(messageRepository.findFirstMessagePreviews(
                List.of(firstId, secondId), Message.MessageRole.USER
        )).thenReturn(List.of(firstPreview));
        when(messageRepository.findConversationIdsWithMessages(List.of(firstId, secondId)))
                .thenReturn(List.of(firstId, secondId));

        List<Conversation> result = conversationService.getUserConversations(userId, "chat");

        assertEquals("第一条用户消息", result.get(0).getPreview());
        assertEquals("第一条用户消息", result.get(0).getTitle());
        assertEquals("暂无预览", result.get(1).getPreview());
        verify(messageRepository, never()).findByConversationIdOrderByCreatedAtAsc(firstId);
        verify(messageRepository, never()).findByConversationIdOrderByCreatedAtAsc(secondId);
    }

    @Test
    void deletesOnlyTheRequestedWorkspace() {
        UUID userId = UUID.randomUUID();
        Conversation agentConversation = conversation(UUID.randomUUID(), userId);
        agentConversation.setWorkspaceMode("agent");
        when(conversationRepository.findRecentConversationsByUserIdAndWorkspaceMode(userId, "agent"))
                .thenReturn(List.of(agentConversation));

        conversationService.deleteAllConversations(userId, "agent");

        verify(conversationRepository).deleteAll(List.of(agentConversation));
        verify(conversationRepository, never()).findByUserId(userId);
    }

    private Conversation conversation(UUID conversationId, UUID userId) {
        Conversation conversation = new Conversation();
        conversation.setId(conversationId);
        conversation.setUserId(userId);
        return conversation;
    }
}
