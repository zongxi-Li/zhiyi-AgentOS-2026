package com.kinlin.ai.service;

import com.kinlin.ai.entity.Conversation;
import com.kinlin.ai.entity.Message;
import com.kinlin.ai.repository.ConversationRepository;
import com.kinlin.ai.repository.MessageRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.UUID;

/**
 * 搜索服务
 * 在当前用户的会话范围内执行跨对话消息搜索
 */
@Service
@RequiredArgsConstructor
public class SearchService {

    private final ConversationRepository conversationRepository;
    private final MessageRepository messageRepository;

    /**
     * 搜索用户会话中包含关键词的消息（最多返回200条）
     */
    public List<Message> searchMessages(UUID userId, String keyword) {
        List<UUID> conversationIds = conversationRepository.findByUserId(userId).stream()
                .map(Conversation::getId)
                .toList();
        if (conversationIds.isEmpty()) {
            return List.of();
        }
        return messageRepository.findByConversationIdInAndContentContainingIgnoreCase(
                conversationIds, keyword, PageRequest.of(0, 200));
    }
}
