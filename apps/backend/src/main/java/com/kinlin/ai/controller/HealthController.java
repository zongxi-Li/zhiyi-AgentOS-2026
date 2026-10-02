package com.kinlin.ai.controller;

import com.kinlin.ai.client.AiDependencyHealthClient;
import com.kinlin.ai.projection.operational.dto.OperationalQuery;
import com.kinlin.ai.projection.operational.mapper.OperationalProjectionMapper;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.http.ResponseEntity;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.connection.RedisConnection;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.HashMap;
import java.util.Map;

/**
 * 健康检查控制器
 *
 * <p>Platform health (postgres/redis) is checked here; Python dependency health is
 * delegated to the narrow {@link AiDependencyHealthClient} — this controller performs
 * no transport itself.</p>
 *
 * <p>Redis 连接工厂按可选依赖注入：prod/compose（cache.type=redis）必有；
 * dev/test/pg-it 显式排除 Redis 自动配置后无该 bean，/ready 将 redis 标记为
 * disabled 而不是让整个上下文无法启动。</p>
 */
@RestController
@RequestMapping("/health")
public class HealthController {

    private final JdbcTemplate jdbcTemplate;
    private final ObjectProvider<RedisConnectionFactory> redisConnectionFactory;
    private final AiDependencyHealthClient aiDependencyHealthClient;

    public HealthController(
            JdbcTemplate jdbcTemplate,
            ObjectProvider<RedisConnectionFactory> redisConnectionFactory,
            AiDependencyHealthClient aiDependencyHealthClient
    ) {
        this.jdbcTemplate = jdbcTemplate;
        this.redisConnectionFactory = redisConnectionFactory;
        this.aiDependencyHealthClient = aiDependencyHealthClient;
    }

    @GetMapping
    public ResponseEntity<OperationalQuery.BasicHealth> health() {
        Map<String, Object> response = new HashMap<>();
        response.put("status", "UP");
        response.put("service", "kinlin-backend");
        response.put("version", "1.0.0");
        return ResponseEntity.ok(OperationalProjectionMapper.health(response));
    }

    @GetMapping("/live")
    public ResponseEntity<OperationalQuery.BasicHealth> live() {
        return ResponseEntity.ok(OperationalProjectionMapper.health(
                Map.of("status", "UP", "service", "kinlin-backend", "check", "liveness")));
    }

    @GetMapping("/ready")
    public ResponseEntity<OperationalQuery.Ready> ready() {
        Map<String, Object> checks = new HashMap<>();
        try {
            checks.put("postgres", jdbcTemplate.queryForObject("SELECT 1", Integer.class) != null);
            RedisConnectionFactory factory = redisConnectionFactory.getIfAvailable();
            if (factory == null) {
                // Redis 自动配置被显式排除的 profile（dev/test/pg-it）：缓存降级为进程内，redis 不参与就绪判定
                checks.put("redis", "disabled");
            } else {
                try (RedisConnection connection = factory.getConnection()) {
                    String pong = connection.ping();
                    checks.put("redis", "PONG".equalsIgnoreCase(pong));
                }
            }
            return ResponseEntity.ok(OperationalProjectionMapper.ready(Map.of("status", "UP", "checks", checks)));
        } catch (Exception e) {
            checks.put("error", e.getClass().getSimpleName());
            return ResponseEntity.status(503).body(OperationalProjectionMapper.ready(Map.of("status", "DOWN", "checks", checks)));
        }
    }

    @GetMapping("/dependencies")
    public ResponseEntity<OperationalQuery.Dependencies> dependencies() {
        AiDependencyHealthClient.AiDependencyHealth ai = aiDependencyHealthClient.probe();
        Map<String, Object> aiService = new HashMap<>();
        aiService.put("status", ai.status());
        if (ai.detail() != null) {
            aiService.put("detail", ai.detail());
        }
        if (ai.errorType() != null) {
            aiService.put("error", ai.errorType());
        }
        aiService.put("affectsReadiness", false);
        return ResponseEntity.ok(OperationalProjectionMapper.dependencies(
                Map.of("status", ai.status(), "dependencies", Map.of("aiService", aiService))));
    }
}
