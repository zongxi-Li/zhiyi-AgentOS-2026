package com.kinlin.ai.config;

import com.kinlin.ai.service.CacheStrategyService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;

/**
 * 缓存预热启动器
 * 应用启动时预热系统缓存
 */
@Slf4j
@Component
@RequiredArgsConstructor
@Order(2) // 在DataInitializer之后执行
public class CacheWarmupRunner implements ApplicationRunner {

    private final CacheStrategyService cacheStrategyService;

    @Override
    public void run(ApplicationArguments args) {
        log.info("开始执行缓存预热...");
        try {
            cacheStrategyService.warmupCache();
            log.info("缓存预热完成");
        } catch (Exception e) {
            log.error("缓存预热失败", e);
        }
    }
}





