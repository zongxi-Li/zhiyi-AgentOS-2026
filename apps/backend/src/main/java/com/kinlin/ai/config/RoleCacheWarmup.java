package com.kinlin.ai.config;

import com.kinlin.ai.service.RoleSwitchOptimizer;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;

/**
 * 角色缓存预热
 * 应用启动时预热常用角色缓存
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class RoleCacheWarmup implements ApplicationRunner {

    private final RoleSwitchOptimizer roleSwitchOptimizer;

    @Override
    public void run(ApplicationArguments args) {
        log.info("开始预热角色缓存...");
        try {
            roleSwitchOptimizer.warmupCommonRoles();
            log.info("角色缓存预热完成");
        } catch (Exception e) {
            log.error("角色缓存预热失败", e);
        }
    }
}





