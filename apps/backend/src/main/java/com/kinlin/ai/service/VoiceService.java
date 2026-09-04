package com.kinlin.ai.service;

import com.kinlin.ai.dto.ChatResponse;
import com.kinlin.ai.dto.VoiceRecognitionResponse;
import com.kinlin.ai.entity.Conversation;
import com.kinlin.ai.entity.Message;
import com.kinlin.ai.repository.ConversationRepository;
import com.kinlin.ai.repository.MessageRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.UUID;

/**
 * 语音服务类
 * 处理语音对话相关业务逻辑
 */
@Service
@RequiredArgsConstructor
public class VoiceService {

    private final ConversationRepository conversationRepository;
    private final MessageRepository messageRepository;
    private final AiService aiService;

    /**
     * 处理语音消息
     */
    @Transactional
    public ChatResponse processVoiceMessage(
            byte[] audioData,
            UUID roleId,
            String contextId,
            UUID userId
    ) {
        // 获取或创建对话
        Conversation conversation = getOrCreateConversation(contextId, userId, roleId);

        // 调用AI服务进行语音识别和生成回复（Python端会一次性处理）
        ChatResponse aiResponse = aiService.sendVoiceMessage(
                audioData, 
                roleId != null ? roleId.toString() : null
        );

        // 从响应中提取识别的文本
        String recognizedText = aiResponse.getRecognizedText();
        if (recognizedText == null || recognizedText.isEmpty()) {
            // 如果没有recognizedText，尝试从text中获取（作为fallback）
            recognizedText = aiResponse.getText();
        }

        // 保存识别的文本（用户消息）
        Message userMessage = new Message();
        userMessage.setConversationId(conversation.getId());
        userMessage.setRole(Message.MessageRole.USER);
        userMessage.setContent(recognizedText);
        userMessage.setMessageType(Message.MessageType.VOICE);
        messageRepository.save(userMessage);

        // 保存AI回复
        Message assistantMessage = new Message();
        assistantMessage.setConversationId(conversation.getId());
        assistantMessage.setRole(Message.MessageRole.ASSISTANT);
        assistantMessage.setContent(aiResponse.getText());
        assistantMessage.setMessageType(Message.MessageType.TEXT);
        messageRepository.save(assistantMessage);

        aiResponse.setContextId(conversation.getContextId());
        // 确保recognizedText被设置
        if (aiResponse.getRecognizedText() == null) {
            aiResponse.setRecognizedText(recognizedText);
        }

        return aiResponse;
    }

    /**
     * 文本转语音
     */
    public byte[] textToSpeech(String text, String voice, Double speed, Double pitch) {
        return aiService.textToSpeech(text, voice, speed, pitch);
    }

    private Conversation getOrCreateConversation(String contextId, UUID userId, UUID roleId) {
        if (contextId != null && !contextId.isEmpty()) {
            return conversationRepository.findByContextId(contextId)
                    .orElseGet(() -> createNewConversation(userId, roleId));
        }
        return createNewConversation(userId, roleId);
    }

    private Conversation createNewConversation(UUID userId, UUID roleId) {
        Conversation conversation = new Conversation();
        conversation.setUserId(userId);
        conversation.setRoleId(roleId);
        conversation.setContextId(UUID.randomUUID().toString());
        return conversationRepository.save(conversation);
    }
}

