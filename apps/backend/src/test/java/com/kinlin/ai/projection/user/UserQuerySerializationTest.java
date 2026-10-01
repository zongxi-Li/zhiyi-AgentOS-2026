package com.kinlin.ai.projection.user;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.entity.User;
import com.kinlin.ai.projection.user.mapper.UserProjectionMapper;
import org.junit.jupiter.api.Test;

import java.time.LocalDateTime;
import java.util.Set;
import java.util.UUID;
import java.util.HashSet;

import static org.junit.jupiter.api.Assertions.*;

class UserQuerySerializationTest {
    @Test
    void serializesOnlyPublicFieldsWithoutReadingOrChangingCredentials() throws Exception {
        User user = new User();
        user.setId(UUID.randomUUID());
        user.setUsername("alice");
        user.setEmail("alice@example.test");
        user.setAvatar("avatars/alice.png");
        user.setPasswordHash("credential-sentinel");
        user.setCreatedAt(LocalDateTime.of(2026, 10, 1, 9, 0));
        user.setUpdatedAt(user.getCreatedAt());

        ObjectMapper mapper = new ObjectMapper().findAndRegisterModules();
        var json = mapper.readTree(mapper.writeValueAsString(UserProjectionMapper.toQuery(user)));
        Set<String> fields = new HashSet<>();
        json.fieldNames().forEachRemaining(fields::add);
        assertEquals(Set.of("id", "username", "email", "avatar", "createdAt", "updatedAt"), fields);
        assertFalse(json.has("passwordHash"));
        assertFalse(json.toString().contains("credential-sentinel"));
        assertEquals(user.getId().toString(), json.get("id").asText());
        assertEquals("alice@example.test", json.get("email").asText());
        assertEquals("credential-sentinel", user.getPasswordHash());
    }
}
