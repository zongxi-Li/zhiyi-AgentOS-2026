package com.kinlin.ai.projection.user.mapper;

import com.kinlin.ai.entity.User;
import com.kinlin.ai.projection.user.dto.UserQuery;

/** Stateless output mapping; the service remains the owner of the entity and its lifecycle. */
public final class UserProjectionMapper {
    private UserProjectionMapper() { }

    public static UserQuery toQuery(User user) {
        return new UserQuery(user.getId(), user.getUsername(), user.getEmail(), user.getAvatar(),
                user.getCreatedAt(), user.getUpdatedAt());
    }
}
