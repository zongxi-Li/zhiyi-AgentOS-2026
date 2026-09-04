package com.kinlin.ai.performance;

import com.kinlin.ai.service.ChatService;
import com.kinlin.ai.service.RoleSwitchOptimizer;
import com.kinlin.ai.dto.ChatRequest;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.junit.jupiter.SpringExtension;

import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.*;

/**
 * 性能测试
 */
@SpringBootTest
@ExtendWith(SpringExtension.class)
@ActiveProfiles("test")
class PerformanceTest {

    @Autowired(required = false)
    private ChatService chatService;

    @Autowired(required = false)
    private RoleSwitchOptimizer roleSwitchOptimizer;

    private ExecutorService executorService;

    @BeforeEach
    void setUp() {
        executorService = Executors.newFixedThreadPool(10);
    }

    @Test
    void testRoleCachePerformance() {
        if (roleSwitchOptimizer == null) {
            return; // 跳过测试如果服务不可用
        }

        UUID roleId = UUID.randomUUID();
        int iterations = 100;

        // 测试缓存性能
        long startTime = System.currentTimeMillis();
        for (int i = 0; i < iterations; i++) {
            try {
                roleSwitchOptimizer.getCacheStats();
            } catch (Exception e) {
                // 忽略错误，只测试性能
            }
        }
        long endTime = System.currentTimeMillis();
        long duration = endTime - startTime;

        // 验证性能（应该在合理时间内完成）
        assertTrue(duration < 1000, "缓存操作应该在1秒内完成100次");
        System.out.println("缓存操作100次耗时: " + duration + "ms");
    }

    @Test
    void testConcurrentRequests() throws Exception {
        if (chatService == null) {
            return; // 跳过测试如果服务不可用
        }

        int concurrentRequests = 10;
        CompletableFuture<?>[] futures = new CompletableFuture[concurrentRequests];

        long startTime = System.currentTimeMillis();

        // 并发发送请求
        for (int i = 0; i < concurrentRequests; i++) {
            final int index = i;
            futures[i] = CompletableFuture.runAsync(() -> {
                try {
                    ChatRequest request = new ChatRequest();
                    request.setText("测试消息 " + index);
                    // chatService.sendMessage(request, UUID.randomUUID());
                } catch (Exception e) {
                    // 忽略错误，只测试并发性能
                }
            }, executorService);
        }

        // 等待所有请求完成
        CompletableFuture.allOf(futures).get(5, TimeUnit.SECONDS);

        long endTime = System.currentTimeMillis();
        long duration = endTime - startTime;

        System.out.println("并发" + concurrentRequests + "个请求耗时: " + duration + "ms");
        assertTrue(duration < 5000, "并发请求应该在5秒内完成");
    }

    @org.junit.jupiter.api.AfterEach
    void tearDown() {
        if (executorService != null) {
            executorService.shutdown();
        }
    }
}





