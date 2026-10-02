package com.kinlin.ai.projection.user;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.entity.User;
import com.kinlin.ai.projection.user.dto.UserQuery;
import com.kinlin.ai.projection.user.mapper.UserProjectionMapper;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.NullAndEmptySource;
import org.junit.jupiter.params.provider.ValueSource;

import java.util.Arrays;
import java.util.Set;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class UserCredentialOutputGuardTest {
    @ParameterizedTest
    @NullAndEmptySource
    @ValueSource(strings = {"credential-sentinel", "$2a$10$stored-hash", "passwordHash"})
    void credentialsAreNeverReadOrSerializedRegardlessOfTheirValue(String hash) throws Exception {
        User source = new User();
        source.setUsername("alice");
        source.setPasswordHash(hash);
        User user = spy(source);
        String encoded = new ObjectMapper().findAndRegisterModules()
                .writeValueAsString(UserProjectionMapper.toQuery(user));
        verify(user, never()).getPasswordHash();
        assertFalse(encoded.contains("passwordHash"));
        if (hash != null && !hash.isEmpty()) { assertFalse(encoded.contains(hash)); }
        assertEquals(Set.of("id", "username", "email", "avatar", "createdAt", "updatedAt"),
                Arrays.stream(UserQuery.class.getRecordComponents()).map(java.lang.reflect.RecordComponent::getName)
                        .collect(Collectors.toSet()));
    }
}
