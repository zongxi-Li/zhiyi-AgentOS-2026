package com.kinlin.ai.config;

import com.fasterxml.jackson.annotation.JsonAutoDetect;
import com.fasterxml.jackson.annotation.JsonTypeInfo;
import com.fasterxml.jackson.annotation.PropertyAccessor;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.databind.jsontype.impl.LaissezFaireSubTypeValidator;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cache.Cache;
import org.springframework.cache.annotation.CachingConfigurer;
import org.springframework.cache.interceptor.CacheErrorHandler;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.data.redis.cache.RedisCacheConfiguration;
import org.springframework.data.redis.cache.RedisCacheManager;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.serializer.GenericJackson2JsonRedisSerializer;
import org.springframework.data.redis.serializer.RedisSerializationContext;
import org.springframework.data.redis.serializer.StringRedisSerializer;

import java.time.Duration;

/**
 * Redis 缓存配置（J1.4B 收敛后）。
 *
 * <p>激活条件：{@code spring.cache.type=redis} 或未设置（matchIfMissing）——
 * 即 canonical/prod/compose；dev/test/pg-it 显式 {@code simple} 时本类退位，
 * 由 Boot 的 ConcurrentMapCacheManager 接管（@EnableCaching 在主应用类上，
 * 不随本类的条件退位而失效）。</p>
 *
 * <p>J1.4B 两处加固：</p>
 * <ul>
 *   <li><b>degrade-to-DB</b>：Redis 不可达时缓存操作降级（get 返回 miss、
 *       put/evict 记 WARN），请求回落数据库，不把核心链路打成 500。</li>
 *   <li><b>序列化器</b>：默认 GenericJackson2JsonRedisSerializer 不注册
 *       JavaTimeModule，缓存 Role 实体（含 LocalDateTime 审计字段）会在
 *       put 时抛 InvalidDefinitionException——真实 Redis 集成测试实证后按
 *       spring-data 官方配方定制（保留 default typing + NullValue 处理）。</li>
 * </ul>
 */
@Slf4j
@Configuration
@ConditionalOnProperty(name = "spring.cache.type", havingValue = "redis", matchIfMissing = true)
public class CacheConfig implements CachingConfigurer {

    @Bean
    public org.springframework.cache.CacheManager cacheManager(RedisConnectionFactory connectionFactory) {
        RedisCacheConfiguration config = RedisCacheConfiguration.defaultCacheConfig()
                .entryTtl(Duration.ofHours(1)) // 缓存1小时
                .serializeKeysWith(RedisSerializationContext.SerializationPair
                        .fromSerializer(new StringRedisSerializer()))
                .serializeValuesWith(RedisSerializationContext.SerializationPair
                        .fromSerializer(roleAwareJsonSerializer()))
                .disableCachingNullValues();

        return RedisCacheManager.builder(connectionFactory)
                .cacheDefaults(config)
                .build();
    }

    /**
     * degrade-to-DB 语义：缓存层任何 Redis 异常都不向业务调用方传播
     * （get → 当 miss 走方法体查库；put/evict/clear → 仅记录 WARN）。
     */
    @Override
    public CacheErrorHandler errorHandler() {
        return new CacheErrorHandler() {
            @Override
            public void handleCacheGetError(RuntimeException exception, Cache cache, Object key) {
                log.warn("Redis cache GET failed, degrading to database: cache={}, error={}",
                        cache.getName(), exception.toString());
            }

            @Override
            public void handleCachePutError(RuntimeException exception, Cache cache, Object key, Object value) {
                log.warn("Redis cache PUT failed: cache={}, error={}",
                        cache.getName(), exception.toString());
            }

            @Override
            public void handleCacheEvictError(RuntimeException exception, Cache cache, Object key) {
                log.warn("Redis cache EVICT failed: cache={}, key={}, error={}",
                        cache.getName(), key, exception.toString());
            }

            @Override
            public void handleCacheClearError(RuntimeException exception, Cache cache) {
                log.warn("Redis cache CLEAR failed: cache={}, error={}",
                        cache.getName(), exception.toString());
            }
        };
    }

    /**
     * 支持 Role 实体（UUID / RoleType 枚举 / JSONB Map / LocalDateTime 审计字段）
     * 稳定往返的 JSON 序列化器。配方对齐 GenericJackson2JsonRedisSerializer
     * 默认构造（default typing NON_FINAL + NullValueSerializer），仅追加
     * JavaTimeModule 并以 ISO 字符串写时间。
     */
    static GenericJackson2JsonRedisSerializer roleAwareJsonSerializer() {
        ObjectMapper mapper = new ObjectMapper();
        mapper.registerModule(new JavaTimeModule());
        mapper.disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);
        mapper.setVisibility(PropertyAccessor.FIELD, JsonAutoDetect.Visibility.ANY);
        mapper.activateDefaultTyping(
                LaissezFaireSubTypeValidator.instance,
                ObjectMapper.DefaultTyping.NON_FINAL,
                JsonTypeInfo.As.PROPERTY);
        return new GenericJackson2JsonRedisSerializer(mapper);
    }
}
