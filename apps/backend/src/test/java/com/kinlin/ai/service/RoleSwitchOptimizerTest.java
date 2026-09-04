package com.kinlin.ai.service;

import com.kinlin.ai.entity.Role;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.Map;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

/**
 * RoleSwitchOptimizer单元测试
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
    void testGetRoleCached_FirstTime() {
        // 准备
        when(roleService.getRole(roleId)).thenReturn(java.util.Optional.of(testRole));

        // 执行
        Role result = optimizer.getRoleCached(roleId);

        // 验证
        assertNotNull(result);
        assertEquals(roleId, result.getId());
        verify(roleService).getRole(roleId);
    }

    @Test
    void testGetRoleCached_Cached() {
        // 准备
        when(roleService.getRole(roleId)).thenReturn(java.util.Optional.of(testRole));

        // 第一次调用
        Role firstResult = optimizer.getRoleCached(roleId);
        
        // 第二次调用（应该从缓存获取）
        Role secondResult = optimizer.getRoleCached(roleId);

        // 验证
        assertNotNull(secondResult);
        assertEquals(roleId, secondResult.getId());
        // 应该只调用一次数据库查询
        verify(roleService, times(1)).getRole(roleId);
    }

    @Test
    void testGetRoleContext() {
        // 准备
        when(roleService.getRole(roleId)).thenReturn(java.util.Optional.of(testRole));

        // 执行
        Map<String, Object> context = optimizer.getRoleContext(roleId);

        // 验证
        assertNotNull(context);
        assertEquals(roleId.toString(), context.get("role_id"));
        assertEquals("测试角色", context.get("name"));
        assertEquals("测试描述", context.get("description"));
    }

    @Test
    void testClearRoleCache() {
        // 准备
        when(roleService.getRole(roleId)).thenReturn(java.util.Optional.of(testRole));
        optimizer.getRoleCached(roleId); // 先缓存

        // 执行
        optimizer.clearRoleCache(roleId);

        // 验证
        Map<String, Object> stats = optimizer.getCacheStats();
        assertEquals(0, stats.get("role_cache_size"));
    }

    @Test
    void testGetCacheStats() {
        // 准备
        when(roleService.getRole(roleId)).thenReturn(java.util.Optional.of(testRole));
        optimizer.getRoleCached(roleId);

        // 执行
        Map<String, Object> stats = optimizer.getCacheStats();

        // 验证
        assertNotNull(stats);
        assertTrue(stats.containsKey("role_cache_size"));
        assertTrue(stats.containsKey("context_cache_size"));
        assertTrue((Integer) stats.get("role_cache_size") >= 0);
    }
}





