package com.kinlin.ai.service;

import com.kinlin.ai.dto.RoleCreateRequest;
import com.kinlin.ai.entity.Role;
import com.kinlin.ai.repository.RoleRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.*;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/**
 * RoleService单元测试
 */
@ExtendWith(MockitoExtension.class)
class RoleServiceTest {

    @Mock
    private RoleRepository roleRepository;

    @Mock
    private RoleValidationService validationService;

    @InjectMocks
    private RoleService roleService;

    private RoleCreateRequest createRequest;
    private UUID userId;

    @BeforeEach
    void setUp() {
        userId = UUID.randomUUID();

        createRequest = new RoleCreateRequest();
        createRequest.setName("测试角色");
        createRequest.setDescription("测试描述");
        createRequest.setSystemPrompt("你是一个测试角色");
    }

    @Test
    void testGetBuiltinRoles() {
        // Given
        Role role = new Role();
        role.setName("律师");
        role.setRoleType(Role.RoleType.BUILTIN);

        when(roleRepository.findByRoleType(Role.RoleType.BUILTIN))
                .thenReturn(List.of(role));

        // When
        List<Role> roles = roleService.getBuiltinRoles();

        // Then
        assertNotNull(roles);
        assertEquals(1, roles.size());
        assertEquals("律师", roles.get(0).getName());
    }

    @Test
    void testCreateRole_Success() {
        // Given
        Role savedRole = new Role();
        savedRole.setId(UUID.randomUUID());
        savedRole.setName("测试角色");

        when(validationService.validateRole(any(Role.class)))
                .thenReturn(new RoleValidationService.ValidationResult(true, Collections.emptyList()));
        when(roleRepository.save(any(Role.class))).thenReturn(savedRole);

        // When
        Role role = roleService.createRole(createRequest, userId);

        // Then
        assertNotNull(role);
        assertEquals("测试角色", role.getName());
        verify(roleRepository).save(any(Role.class));
    }

    @Test
    void testUpdateRole_Success() {
        // Given
        UUID roleId = UUID.randomUUID();
        Role existingRole = new Role();
        existingRole.setId(roleId);
        existingRole.setRoleType(Role.RoleType.CUSTOM);
        existingRole.setUserId(userId);

        Role updatedRole = new Role();
        updatedRole.setId(roleId);
        updatedRole.setName("更新后的角色");

        when(roleRepository.findById(roleId)).thenReturn(Optional.of(existingRole));
        when(validationService.validateRole(any(Role.class)))
                .thenReturn(new RoleValidationService.ValidationResult(true, Collections.emptyList()));
        when(roleRepository.save(any(Role.class))).thenReturn(updatedRole);

        // When
        Optional<Role> result = roleService.updateRole(roleId, createRequest, userId);

        // Then
        assertTrue(result.isPresent());
        assertEquals("更新后的角色", result.get().getName());
    }

    @Test
    void testDeleteRole_Success() {
        // Given
        UUID roleId = UUID.randomUUID();
        Role role = new Role();
        role.setId(roleId);
        role.setRoleType(Role.RoleType.CUSTOM);
        role.setUserId(userId);

        when(roleRepository.findById(roleId)).thenReturn(Optional.of(role));

        // When
        boolean result = roleService.deleteRole(roleId, userId);

        // Then
        assertTrue(result);
        verify(roleRepository).delete(role);
    }

    @Test
    void testDeleteRole_NotFound() {
        // Given
        UUID roleId = UUID.randomUUID();
        when(roleRepository.findById(roleId)).thenReturn(Optional.empty());

        // When
        boolean result = roleService.deleteRole(roleId, userId);

        // Then
        assertFalse(result);
        verify(roleRepository, never()).delete(any(Role.class));
    }
}

