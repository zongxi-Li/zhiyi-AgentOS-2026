package com.kinlin.ai.mapper;

import com.kinlin.ai.dto.MessageResponse;
import com.kinlin.ai.entity.Message;
import org.mapstruct.Mapper;
import org.mapstruct.Mapping;
import org.mapstruct.factory.Mappers;

/**
 * 消息映射器
 */
@Mapper(componentModel = "spring")
public interface MessageMapper {

    MessageMapper INSTANCE = Mappers.getMapper(MessageMapper.class);

    @Mapping(target = "role", expression = "java(message.getRole().name())")
    @Mapping(target = "messageType", expression = "java(message.getMessageType().name())")
    MessageResponse toResponse(Message message);
}

