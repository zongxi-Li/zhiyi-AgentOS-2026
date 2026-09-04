package com.kinlin.ai.service;

import com.kinlin.ai.entity.Role;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.HashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

/**
 * RoleValidationService单元测试
 */
@ExtendWith(MockitoExtension.class)
class RoleValidationServiceTest {

    @InjectMocks
    private RoleValidationService validationService;

    private Role role;

    @BeforeEach
    void setUp() {
        role = new Role();
        role.setName("测试角色");
        role.setDescription("测试描述");
        role.setSystemPrompt("你是一个测试角色");
    }

    @Test
    void testValidateRole_Valid() {
        // When
        var result = validationService.validateRole(role);

        // Then
        assertTrue(result.valid());
        assertTrue(result.errors().isEmpty());
    }

    @Test
    void testValidateRole_EmptyName() {
        // Given
        role.setName("");

        // When
        var result = validationService.validateRole(role);

        // Then
        assertFalse(result.valid());
        assertTrue(result.errors().contains("角色名称不能为空"));
    }

    @Test
    void testValidateRole_EmptySystemPrompt() {
        // Given
        role.setSystemPrompt("");

        // When
        var result = validationService.validateRole(role);

        // Then
        assertFalse(result.valid());
        assertTrue(result.errors().contains("系统提示词不能为空"));
    }

    @Test
    void testValidateRole_InvalidFormality() {
        // Given
        Map<String, Object> style = new HashMap<>();
        style.put("formality", 1.5); // 超出范围
        role.setDialogueStyle(style);

        // When
        var result = validationService.validateRole(role);

        // Then
        assertFalse(result.valid());
        assertTrue(result.errors().stream()
                .anyMatch(e -> e.contains("正式度")));
    }

    @Test
    void testValidateRole_ValidDialogueStyle() {
        // Given
        Map<String, Object> style = new HashMap<>();
        style.put("formality", 0.8);
        style.put("warmth", 0.6);
        role.setDialogueStyle(style);

        // When
        var result = validationService.validateRole(role);

        // Then
        assertTrue(result.valid());
    }
}

