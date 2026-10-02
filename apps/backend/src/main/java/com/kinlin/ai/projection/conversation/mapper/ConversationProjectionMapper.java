package com.kinlin.ai.projection.conversation.mapper;

import com.kinlin.ai.entity.Conversation;
import com.kinlin.ai.projection.conversation.dto.ConversationDetailQuery;
import com.kinlin.ai.projection.conversation.dto.ConversationQuery;

/** Pure output adapter over service results; no service, repository, transport or cache calls. */
public final class ConversationProjectionMapper {
    private ConversationProjectionMapper() { }

    public static ConversationQuery toQuery(Conversation conversation) {
        return new ConversationQuery(conversation.getId(), conversation.getUserId(), conversation.getRoleId(),
                conversation.getContextId(), conversation.getTitle(), conversation.getWorkspaceMode(),
                conversation.getPreview(), conversation.getCreatedAt(), conversation.getUpdatedAt());
    }

    public static ConversationDetailQuery toDetail(Conversation conversation, String preview) {
        return new ConversationDetailQuery(toQuery(conversation), preview);
    }
}
