package com.kinlin.ai.service;

import com.kinlin.ai.entity.Role;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cache.annotation.CacheEvict;
import org.springframework.cache.annotation.CachePut;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.UUID;

/**
 * 缓存策略服务
 * 实现对话缓存、角色缓存等
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class CacheStrategyService {

    private final CacheService cacheService;
    private final RoleService roleService;

    /**
     * 缓存对话历史
     */
    @Cacheable(value = "conversationHistory", key = "#contextId")
    public List<?> cacheConversationHistory(String contextId, List<?> messages) {
        log.debug("Caching conversation history for contextId: {}", contextId);
        return messages;
    }

    /**
     * 缓存角色信息
     */
    @Cacheable(value = "roleInfo", key = "#roleId")
    public Object cacheRoleInfo(UUID roleId, Object role) {
        log.debug("Caching role info for roleId: {}", roleId);
        return role;
    }

    /**
     * 更新角色缓存
     */
    @CachePut(value = "roleInfo", key = "#roleId")
    public Object updateRoleCache(UUID roleId, Object role) {
        log.debug("Updating role cache for roleId: {}", roleId);
        return role;
    }

    /**
     * 清除角色缓存
     */
    @CacheEvict(value = "roleInfo", key = "#roleId")
    public void evictRoleCache(UUID roleId) {
        log.debug("Evicting role cache for roleId: {}", roleId);
    }

    /**
     * 清除对话缓存
     */
    @CacheEvict(value = "conversationHistory", key = "#contextId")
    public void evictConversationCache(String contextId) {
        log.debug("Evicting conversation cache for contextId: {}", contextId);
    }

    /**
     * 预热缓存
     */
    public void warmupCache() {
        log.info("Warming up cache...");
        try {
            // 预热内置角色缓存
            warmupBuiltinRoles();
            
            // 预热常用对话上下文（如果有）
            warmupRecentConversations();
            
            log.info("Cache warmup completed successfully");
        } catch (Exception e) {
            log.error("Cache warmup failed", e);
        }
    }
    
    /**
     * 预热内置角色缓存
     */
    private void warmupBuiltinRoles() {
        try {
            log.debug("Warming up builtin roles cache...");
            List<Role> builtinRoles = roleService.getBuiltinRoles();
            for (Role role : builtinRoles) {
                // 缓存每个内置角色
                cacheRoleInfo(role.getId(), role);
            }
            log.info("Warmed up {} builtin roles", builtinRoles.size());
        } catch (Exception e) {
            log.warn("Failed to warmup builtin roles cache", e);
        }
    }
    
    /**
     * 预热最近对话缓存
     */
    private void warmupRecentConversations() {
        try {
            log.debug("Warming up recent conversations cache...");
            // 实际实现时，可以获取最近的对话并缓存
        } catch (Exception e) {
            log.warn("Failed to warmup recent conversations cache", e);
        }
    }
}

