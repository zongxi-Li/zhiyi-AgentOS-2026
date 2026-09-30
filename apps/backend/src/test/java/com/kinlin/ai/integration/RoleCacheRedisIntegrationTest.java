package com.kinlin.ai.integration;

import com.kinlin.ai.dto.RoleCreateRequest;
import com.kinlin.ai.entity.Role;
import com.kinlin.ai.repository.RoleRepository;
import com.kinlin.ai.service.RoleService;
import com.kinlin.ai.service.RoleSwitchOptimizer;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.MethodOrderer;
import org.junit.jupiter.api.Order;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestMethodOrder;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.SpyBean;
import org.springframework.cache.Cache;
import org.springframework.cache.CacheManager;

import java.util.Map;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;

/**
 * J1.4B §十四/§十五/§十六：真实 Redis 上的角色缓存契约。
 *
 * <p>权威唯一化后的验收：Spring Cache（RedisCacheManager "roles"）是唯一
 * cache owner，@CacheEvict 写路径逐出在真实 Redis 上跨实例语义成立
 * （共享存储）；Role 实体（UUID/枚举/JSONB Map/LocalDateTime）可稳定
 * 序列化往返；Redis 不可用时 degrade-to-DB，核心读路径不失败。</p>
 */
@SpringBootTest
@TestMethodOrder(MethodOrderer.OrderAnnotation.class)
class RoleCacheRedisIntegrationTest extends RedisIntegrationTestBase {

    @Autowired
    private RoleSwitchOptimizer optimizer;

    @SpyBean
    private RoleService roleService;

    @Autowired
    private CacheManager cacheManager;

    @Autowired
    private RoleRepository roleRepository;

    @BeforeEach
    void resetCacheAndSpy() {
        Cache cache = cacheManager.getCache("roles");
        if (cache != null) {
            cache.clear();
        }
        org.mockito.Mockito.clearInvocations(roleService);
    }

    private Role createCustomRole(String name) {
        RoleCreateRequest request = new RoleCreateRequest();
        request.setName(name);
        request.setSystemPrompt("你是" + name + "，用于 J1.4B Redis 缓存契约测试。");
        request.setDescription("redis-it fixture");
        request.setDialogueStyle(new java.util.HashMap<>(Map.of(
                "formality", 0.7, "warmth", 0.4, "technical_level", 0.6)));
        request.setPersonality(new java.util.HashMap<>(Map.of(
                "严谨", true, "耐心", false)));
        return roleService.createRole(request, UUID.randomUUID());
    }

    @Test
    @Order(1)
    void cacheMissLoadsFromDatabaseExactlyOnceThenHitsCache() {
        Role role = createCustomRole("缓存未命中测试_" + UUID.randomUUID());
        UUID roleId = role.getId();

        Role firstRead = optimizer.getRoleCached(roleId);
        Role secondRead = optimizer.getRoleCached(roleId);

        assertThat(firstRead.getId()).isEqualTo(roleId);
        assertThat(secondRead.getId()).isEqualTo(roleId);
        // 两次读取只触发一次数据库加载：第二次命中 Redis 缓存
        verify(roleService, times(1)).getRole(roleId);
    }

    @Test
    @Order(2)
    void roleEntityRoundTripsThroughRedisSerialization() {
        Role role = createCustomRole("序列化往返测试_" + UUID.randomUUID());
        optimizer.getRoleCached(role.getId());

        Cache cache = cacheManager.getCache("roles");
        assertThat(cache).isNotNull();
        Role cached = cache.get(role.getId(), Role.class);

        assertThat(cached).isNotNull();
        // UUID 主键
        assertThat(cached.getId()).isEqualTo(role.getId());
        // 枚举
        assertThat(cached.getRoleType()).isEqualTo(Role.RoleType.CUSTOM);
        // JSONB Map（含中文键、double、boolean）
        assertThat(cached.getDialogueStyle()).isEqualTo(role.getDialogueStyle());
        assertThat(cached.getPersonality()).isEqualTo(role.getPersonality());
        // LocalDateTime 审计字段（默认序列化器不装 JavaTimeModule 会在 put 时炸）。
        // 与数据库真值对表而非与内存实体对表：DB 时间戳为微秒精度，内存审计字段带纳秒
        assertThat(roleRepository.findById(role.getId())).hasValueSatisfying(dbRole -> {
            assertThat(cached.getCreatedAt()).isEqualTo(dbRole.getCreatedAt());
            assertThat(cached.getUpdatedAt()).isEqualTo(dbRole.getUpdatedAt());
        });
    }

    @Test
    @Order(3)
    void updateEvictsCacheAndPreventsStaleValue() {
        String suffix = UUID.randomUUID().toString();
        Role role = createCustomRole("更新前名字_" + suffix);
        UUID roleId = role.getId();

        Role stale = optimizer.getRoleCached(roleId);
        assertThat(stale.getName()).isEqualTo("更新前名字_" + suffix);
        verify(roleService, times(1)).getRole(roleId);

        RoleCreateRequest update = new RoleCreateRequest();
        update.setName("更新后名字_" + suffix);
        update.setSystemPrompt("更新后的提示词。");
        roleService.updateRole(roleId, update, role.getUserId());

        // @CacheEvict 逐出后重新加载，绝不允许返回 stale 值
        Role fresh = optimizer.getRoleCached(roleId);
        assertThat(fresh.getName()).isEqualTo("更新后名字_" + suffix);
        verify(roleService, times(2)).getRole(roleId);
    }

    @Test
    @Order(4)
    void deleteEvictsCacheSoDeletedRoleIsNotServed() {
        String suffix = UUID.randomUUID().toString();
        Role role = createCustomRole("删除缓存测试_" + suffix);
        UUID roleId = role.getId();

        optimizer.getRoleCached(roleId);
        assertThat(roleService.deleteRole(roleId, role.getUserId())).isTrue();

        assertThatThrownBy(() -> optimizer.getRoleCached(roleId))
                .isInstanceOf(RuntimeException.class)
                .hasMessageContaining("角色不存在");
        verify(roleService, times(2)).getRole(roleId);
        assertThat(roleRepository.findById(roleId)).isEmpty();
    }

    /**
     * §十五：Redis 被定义为 optional cache——不可用时核心 DB 路径仍可工作
     * （degrade-to-DB，CacheConfig 的 CacheErrorHandler 吞掉缓存异常）。
     * 必须保持最后一个执行：共享 Redis 容器停掉后不再重启（重启会分配
     * 新端口，而应用上下文持旧端口），后续也无需再用。
     */
    @Test
    @Order(5)
    void redisUnavailableDegradesToDatabase() {
        Role role = createCustomRole("降级测试_" + UUID.randomUUID());
        UUID roleId = role.getId();
        optimizer.getRoleCached(roleId);
        verify(roleService, times(1)).getRole(roleId);

        REDIS.stop();

        long start = System.currentTimeMillis();
        Role degraded = optimizer.getRoleCached(roleId);
        long elapsed = System.currentTimeMillis() - start;

        // 缓存层失败不向调用方传播：照常从数据库返回
        assertThat(degraded.getId()).isEqualTo(roleId);
        // Lettuce 命令超时（canonical 2000ms）内完成降级，不长时间挂起
        assertThat(elapsed).isLessThan(10_000);
        verify(roleService, times(2)).getRole(roleId);
    }
}
