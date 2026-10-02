package com.kinlin.ai.service;

import com.kinlin.ai.entity.Role;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;

import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

/**
 * 角色切换缓存服务（J1.4B 收敛后）
 *
 * <p>缓存权威唯一化：Spring Cache（生产 = RedisCacheManager "roles"，TTL 1h）是
 * 唯一共享 cache owner。JVM 本地双层缓存（可变实体 Map + 派生上下文 Map）已删除——
 * 它缓存可变 Role 实体、跨实例不同步、且本地逐出方法只清本地不清 Redis，
 * 曾导致角色更新后最长 1 小时 stale。</p>
 *
 * <p>失效协议：RoleService 的 update/delete 写路径用 @CacheEvict 精确逐出，
 * Redis 为共享存储，多实例部署时任意实例的写对所有实例生效。</p>
 *
 * <p>Redis 不可用时按 degrade-to-DB 语义降级（CacheConfig 的 CacheErrorHandler），
 * 请求回落数据库，不阻断核心链路。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class RoleSwitchOptimizer {

    private final RoleService roleService;

    /**
     * 获取角色（Spring Cache "roles"，miss 时由数据库加载）。
     */
    @Cacheable(value = "roles", key = "#roleId")
    public Role getRoleCached(UUID roleId) {
        Role role = roleService.getRole(roleId)
                .orElseThrow(() -> new RuntimeException("角色不存在: " + roleId));
        log.debug("从数据库加载角色: {}", roleId);
        return role;
    }

    /**
     * 获取角色上下文（快速访问）。
     *
     * <p>纯派生数据，按需从缓存的 Role 构建，不再维护第二份本地缓存——
     * 构建成本为单对象字段拷贝，此前"预加载"无真实性能证据。</p>
     */
    public Map<String, Object> getRoleContext(UUID roleId) {
        Role role = getRoleCached(roleId);
        return buildRoleContext(role);
    }

    /**
     * 构建角色上下文
     */
    private Map<String, Object> buildRoleContext(Role role) {
        Map<String, Object> context = new HashMap<>();

        context.put("role_id", role.getId().toString());
        context.put("name", role.getName());
        context.put("description", role.getDescription());
        context.put("personality", role.getPersonality());
        context.put("system_prompt", role.getSystemPrompt());
        context.put("dialogue_style", role.getDialogueStyle());

        return context;
    }

    /**
     * 预热内置角色（启动期，数量固定且极小，有界成本；失败不阻止应用启动）。
     */
    public void warmupCommonRoles() {
        log.info("开始预热常用角色...");

        try {
            // 获取所有内置角色
            var builtinRoles = roleService.getBuiltinRoles();

            for (Role role : builtinRoles) {
                try {
                    getRoleCached(role.getId());
                    log.debug("预热角色: {}", role.getName());
                } catch (Exception e) {
                    log.warn("预热角色失败: {}", role.getId(), e);
                }
            }

            log.info("常用角色预热完成，共预热 {} 个角色", builtinRoles.size());
        } catch (Exception e) {
            log.error("预热常用角色失败", e);
        }
    }
}
