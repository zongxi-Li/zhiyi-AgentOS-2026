package com.kinlin.ai.projection.conversation.dto;

/** Conversation detail envelope replacing the previous Map body; preview stays a plain string. */
public record ConversationDetailQuery(
        ConversationQuery conversation,
        String preview
) { }
