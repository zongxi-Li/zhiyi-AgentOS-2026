package com.kinlin.ai.service;

import com.kinlin.ai.entity.Role;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

/**
 * RoleSwitchOptimizer 单元测试（J1.4B 收敛后）。
 *
 * <p>本地 ConcurrentHashMap 双层缓存已删除，缓存职责整体移交 Spring Cache
 * （单元测试无缓存代理，@Cacheable 直通；真实缓存命中/逐出/序列化由
 * {@code RoleCacheRedisIntegrationTest} 在 Testcontainers Redis 上验证）。
 * 本测试锁定：委托关系、上下文派生、内置角色预热有界性。</p>
 */
@ExtendWith(MockitoExtension.class)
class RoleSwitchOptimizerTest {

    @Mock
    private RoleService roleService;

    private RoleSwitchOptimizer optimizer;

    private UUID roleId;
    private Role testRole;

    @BeforeEach
    void setUp() {
        optimizer = new RoleSwitchOptimizer(roleService);
        roleId = UUID.randomUUID();

        testRole = new Role();
        testRole.setId(roleId);
        testRole.setName("测试角色");
        testRole.setDescription("测试描述");
    }

    @Test
    void getRoleCachedDelegatesToRoleService() {
        when(roleService.getRole(roleId)).thenReturn(java.util.Optional.of(testRole));

        Role result = optimizer.getRoleCached(roleId);

        assertNotNull(result);
        assertEquals(roleId, result.getId());
        verify(roleService).getRole(roleId);
    }

    @Test
    void getRoleCachedThrowsWhenRoleMissing() {
        when(roleService.getRole(roleId)).thenReturn(java.util.Optional.empty());

        RuntimeException exception = assertThrows(RuntimeException.class,
                () -> optimizer.getRoleCached(roleId));

        assertTrue(exception.getMessage().contains("角色不存在"));
    }

    @Test
    void getRoleContextDerivesFromCachedRoleOnDemand() {
        when(roleService.getRole(roleId)).thenReturn(java.util.Optional.of(testRole));

        Map<String, Object> context = optimizer.getRoleContext(roleId);

        assertNotNull(context);
        assertEquals(roleId.toString(), context.get("role_id"));
        assertEquals("测试角色", context.get("name"));
        assertEquals("测试描述", context.get("description"));
    }

    @Test
    void warmupLoadsEveryBuiltinRoleAndSurvivesFailures() {
        Role failing = new Role();
        failing.setId(UUID.randomUUID());
        failing.setName("坏角色");
        when(roleService.getBuiltinRoles()).thenReturn(List.of(testRole, failing));
        when(roleService.getRole(testRole.getId())).thenReturn(java.util.Optional.of(testRole));
        when(roleService.getRole(failing.getId())).thenReturn(java.util.Optional.empty());

        assertDoesNotThrow(() -> optimizer.warmupCommonRoles());

        // 每个内置角色都尝试预热，单个失败不中断（RoleCacheWarmup 契约）
        verify(roleService).getRole(testRole.getId());
        verify(roleService).getRole(failing.getId());
    }
}
