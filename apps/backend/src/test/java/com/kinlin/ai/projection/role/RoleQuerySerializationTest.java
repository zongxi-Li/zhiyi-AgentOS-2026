package com.kinlin.ai.projection.role;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.entity.Role;
import com.kinlin.ai.projection.role.mapper.RoleProjectionMapper;
import org.junit.jupiter.api.Test;

import java.util.*;

import static org.junit.jupiter.api.Assertions.*;

class RoleQuerySerializationTest {
    private final ObjectMapper json = new ObjectMapper().findAndRegisterModules();

    @Test
    void preservesCustomConfigurationRoundTripsWithAnExplicitIdentityWhitelist() throws Exception {
        Role role = role();
        Map<String, Object> configuration = json.readValue(
                "{\"formality\":0.9,\"custom\":{\"tags\":[\"中文\",7,true,null],\"nothing\":null},\"empty\":{}}",
                new com.fasterxml.jackson.core.type.TypeReference<Map<String, Object>>() { });
        role.setDialogueStyle(configuration);
        role.setPersonality(Map.of("customTrait", true));
        role.setAvatarConfig(Map.of("colors", List.of("red", "blue"), "style", "custom"));
        var projected = RoleProjectionMapper.toQuery(role);
        var encoded = json.readTree(json.writeValueAsString(projected));
        Set<String> fields = new HashSet<>();
        encoded.fieldNames().forEachRemaining(fields::add);
        assertEquals(Set.of("id", "name", "description", "roleType", "userId", "stableKey",
                "systemPrompt", "dialogueStyle", "personality", "avatarConfig", "createdAt", "updatedAt"), fields);
        assertEquals(json.readTree(json.writeValueAsString(configuration)), encoded.get("dialogueStyle"));
        assertEquals(json.readTree(json.writeValueAsString(role.getPersonality())), encoded.get("personality"));
        assertEquals(json.readTree(json.writeValueAsString(role.getAvatarConfig())), encoded.get("avatarConfig"));
        assertEquals("CUSTOM", encoded.get("roleType").asText());
        assertEquals("public prompt", encoded.get("systemPrompt").asText());
        configuration.put("later", "not part of snapshot");
        assertFalse(json.readTree(json.writeValueAsString(projected)).get("dialogueStyle").has("later"));
        assertThrows(UnsupportedOperationException.class, () -> projected.dialogueStyle().properties().clear());
    }

    @Test
    void preservesNullAndEmptyConfigurationObjects() throws Exception {
        Role role = role();
        role.setPersonality(Map.of());
        var encoded = json.readTree(json.writeValueAsString(RoleProjectionMapper.toQuery(role)));
        assertTrue(encoded.get("dialogueStyle").isNull());
        assertTrue(encoded.get("personality").isObject());
        assertEquals(0, encoded.get("personality").size());
        assertTrue(encoded.get("avatarConfig").isNull());
        role.setRoleType(null);
        assertNull(RoleProjectionMapper.toQuery(role).roleType());
    }

    @Test
    void contextKeepsSnakeCaseAndRejectsUnknownOuterFields() throws Exception {
        Map<String, Object> context = new HashMap<>();
        context.put("role_id", "role-1");
        context.put("name", "custom");
        context.put("description", "description");
        context.put("system_prompt", "prompt");
        context.put("dialogue_style", Map.of("extension", "kept"));
        context.put("personality", Map.of("patient", true));
        context.put("unexpectedInternalField", "must not leave mapper");
        var encoded = json.readTree(json.writeValueAsString(RoleProjectionMapper.toContext(context)));
        Set<String> fields = new HashSet<>();
        encoded.fieldNames().forEachRemaining(fields::add);
        assertEquals(Set.of("role_id", "name", "description", "system_prompt", "dialogue_style", "personality"), fields);
        assertEquals("kept", encoded.get("dialogue_style").get("extension").asText());
        assertEquals(7, context.size());
    }

    @Test
    void cannotRetainArbitraryJavaModelsInsideConfiguration() {
        Role role = role();
        role.setPersonality(Map.of("hiddenEntity", role));
        assertThrows(IllegalArgumentException.class, () -> RoleProjectionMapper.toQuery(role));
    }

    private Role role() {
        Role role = new Role();
        role.setId(UUID.randomUUID());
        role.setName("custom");
        role.setRoleType(Role.RoleType.CUSTOM);
        role.setUserId(UUID.randomUUID());
        role.setSystemPrompt("public prompt");
        return role;
    }
}
