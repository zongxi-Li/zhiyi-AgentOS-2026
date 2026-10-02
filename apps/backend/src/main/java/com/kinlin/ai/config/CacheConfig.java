package com.kinlin.ai.config;

import com.fasterxml.jackson.annotation.JsonAutoDetect;
import com.fasterxml.jackson.annotation.JsonTypeInfo;
import com.fasterxml.jackson.annotation.PropertyAccessor;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.databind.jsontype.impl.LaissezFaireSubTypeValidator;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import io.micrometer.core.instrument.MeterRegistry;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.cache.Cache;
import org.springframework.cache.CacheManager;
import org.springframework.cache.annotation.CachingConfigurer;
import org.springframework.cache.interceptor.CacheErrorHandler;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.cache.RedisCacheConfiguration;
import org.springframework.data.redis.cache.RedisCacheManager;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.serializer.GenericJackson2JsonRedisSerializer;
import org.springframework.data.redis.serializer.RedisSerializationContext;
import org.springframework.data.redis.serializer.StringRedisSerializer;

import java.time.Duration;
import java.util.Collection;
import java.util.concurrent.Callable;

/**
 * Redis 缓存配置（J1.4B 收敛 + J1.4C 窄仪表）。
 *
 * <p>激活条件：{@code spring.cache.type=redis} 或未设置（matchIfMissing）——
 * 即 canonical/prod/compose；dev/test/pg-it 显式 {@code simple} 时本类退位，
 * 由 Boot 的 ConcurrentMapCacheManager 接管（@EnableCaching 在主应用类上，
 * 不随本类的条件退位而失效）。</p>
 *
 * <p>J1.4B/C 三处加固：</p>
 * <ul>
 *   <li><b>degrade-to-DB</b>：Redis 不可达时缓存操作降级（get 返回 miss、
 *       put/evict 记 WARN），请求回落数据库，不把核心链路打成 500。</li>
 *   <li><b>序列化器</b>：默认 GenericJackson2JsonRedisSerializer 不注册
 *       JavaTimeModule，缓存 Role 实体（含 LocalDateTime 审计字段）会在
 *       put 时抛 InvalidDefinitionException——真实 Redis 集成测试实证后按
 *       spring-data 官方配方定制（保留 default typing + NullValue 处理）。</li>
 *   <li><b>窄仪表</b>：hit/miss/put/evict/error 计数以薄装饰器实现
 *       （meter 名对齐 Micrometer binder 惯例：cache.gets{cache,result}、
 *       cache.puts、cache.evictions、cache.errors）。Boot 的
 *       CacheMetricsRegistrar 依赖启动期绑定与自动装配排序，对首访才物化的
 *       Redis 缓存不可靠（redis-it 上下文实测零 meters），故按授权走窄实现；
 *       只加计数不改缓存架构。</li>
 * </ul>
 */
@Slf4j
@Configuration
@ConditionalOnProperty(name = "spring.cache.type", havingValue = "redis", matchIfMissing = true)
public class CacheConfig implements CachingConfigurer {

    @Bean
    public CacheManager cacheManager(RedisConnectionFactory connectionFactory, MeterRegistry meterRegistry) {
        RedisCacheConfiguration config = RedisCacheConfiguration.defaultCacheConfig()
                .entryTtl(Duration.ofHours(1)) // 缓存1小时
                .serializeKeysWith(RedisSerializationContext.SerializationPair
                        .fromSerializer(new StringRedisSerializer()))
                .serializeValuesWith(RedisSerializationContext.SerializationPair
                        .fromSerializer(roleAwareJsonSerializer()))
                .disableCachingNullValues();

        return new InstrumentedCacheManager(
                RedisCacheManager.builder(connectionFactory).cacheDefaults(config).build(),
                meterRegistry);
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

    /** 每个缓存名对应一个装饰后的 Cache；getCacheNames 透传。 */
    static final class InstrumentedCacheManager implements CacheManager {

        private final CacheManager delegate;
        private final MeterRegistry registry;

        InstrumentedCacheManager(CacheManager delegate, MeterRegistry registry) {
            this.delegate = delegate;
            this.registry = registry;
        }

        @Override
        public Cache getCache(String name) {
            Cache nativeCache = delegate.getCache(name);
            return nativeCache == null ? null : new InstrumentedCache(name, nativeCache, registry);
        }

        @Override
        public Collection<String> getCacheNames() {
            return delegate.getCacheNames();
        }
    }

    /** 薄计数层：记录并原样上抛（degrade 语义仍由 CacheErrorHandler 统一裁决）。 */
    static final class InstrumentedCache implements Cache {

        private final String name;
        private final Cache delegate;
        private final MeterRegistry registry;

        InstrumentedCache(String name, Cache delegate, MeterRegistry registry) {
            this.name = name;
            this.delegate = delegate;
            this.registry = registry;
        }

        @Override
        public String getName() {
            return name;
        }

        @Override
        public Object getNativeCache() {
            return delegate.getNativeCache();
        }

        @Override
        public ValueWrapper get(Object key) {
            try {
                ValueWrapper value = delegate.get(key);
                recordGet(value != null);
                return value;
            } catch (RuntimeException error) {
                recordError();
                throw error;
            }
        }

        @Override
        public <T> T get(Object key, Class<T> type) {
            try {
                T value = delegate.get(key, type);
                recordGet(value != null);
                return value;
            } catch (RuntimeException error) {
                recordError();
                throw error;
            }
        }

        @Override
        public <T> T get(Object key, Callable<T> valueLoader) {
            return delegate.get(key, valueLoader);
        }

        @Override
        public void put(Object key, Object value) {
            try {
                delegate.put(key, value);
                registry.counter("cache.puts", "cache", name).increment();
            } catch (RuntimeException error) {
                recordError();
                throw error;
            }
        }

        @Override
        public void evict(Object key) {
            try {
                delegate.evict(key);
                registry.counter("cache.evictions", "cache", name).increment();
            } catch (RuntimeException error) {
                recordError();
                throw error;
            }
        }

        @Override
        public void clear() {
            try {
                delegate.clear();
                registry.counter("cache.clears", "cache", name).increment();
            } catch (RuntimeException error) {
                recordError();
                throw error;
            }
        }

        private void recordGet(boolean hit) {
            registry.counter("cache.gets", "cache", name, "result", hit ? "hit" : "miss").increment();
        }

        private void recordError() {
            registry.counter("cache.errors", "cache", name).increment();
        }
    }
}
