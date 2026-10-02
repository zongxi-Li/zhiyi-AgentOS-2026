package com.kinlin.ai;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.cache.annotation.EnableCaching;
import org.springframework.data.jpa.repository.config.EnableJpaAuditing;

/**
 * 知弈 后端应用主类
 *
 * @author 知弈 Team
 * @version 1.0.0
 */
@SpringBootApplication
@EnableJpaAuditing
// @EnableCaching 放主类：不随 CacheConfig 的 spring.cache.type 条件退位。
// prod/compose 走 CacheConfig 的 RedisCacheManager；dev/test 的
// cache.type=simple 由 Boot 自动装配 ConcurrentMapCacheManager 接管。
@EnableCaching
public class KinlinAiApplication {

    public static void main(String[] args) {
        SpringApplication.run(KinlinAiApplication.class, args);
    }
}

