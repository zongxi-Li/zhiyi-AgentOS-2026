package com.kinlin.ai.controller;

import com.kinlin.ai.infrastructure.http.AiDependencyHealthClient;
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
 */
@RestController
@RequestMapping("/health")
public class HealthController {

    private final JdbcTemplate jdbcTemplate;
    private final RedisConnectionFactory redisConnectionFactory;
    private final AiDependencyHealthClient aiDependencyHealthClient;

    public HealthController(
            JdbcTemplate jdbcTemplate,
            RedisConnectionFactory redisConnectionFactory,
            AiDependencyHealthClient aiDependencyHealthClient
    ) {
        this.jdbcTemplate = jdbcTemplate;
        this.redisConnectionFactory = redisConnectionFactory;
        this.aiDependencyHealthClient = aiDependencyHealthClient;
    }

    @GetMapping
    public ResponseEntity<Map<String, Object>> health() {
        Map<String, Object> response = new HashMap<>();
        response.put("status", "UP");
        response.put("service", "kinlin-backend");
        response.put("version", "1.0.0");
        return ResponseEntity.ok(response);
    }

    @GetMapping("/live")
    public ResponseEntity<Map<String, Object>> live() {
        return ResponseEntity.ok(Map.of("status", "UP", "service", "kinlin-backend", "check", "liveness"));
    }

    @GetMapping("/ready")
    public ResponseEntity<Map<String, Object>> ready() {
        Map<String, Object> checks = new HashMap<>();
        try {
            checks.put("postgres", jdbcTemplate.queryForObject("SELECT 1", Integer.class) != null);
            try (RedisConnection connection = redisConnectionFactory.getConnection()) {
                String pong = connection.ping();
                checks.put("redis", "PONG".equalsIgnoreCase(pong));
            }
            return ResponseEntity.ok(Map.of("status", "UP", "checks", checks));
        } catch (Exception e) {
            checks.put("error", e.getClass().getSimpleName());
            return ResponseEntity.status(503).body(Map.of("status", "DOWN", "checks", checks));
        }
    }

    @GetMapping("/dependencies")
    public ResponseEntity<Map<String, Object>> dependencies() {
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
        return ResponseEntity.ok(Map.of("status", ai.status(), "dependencies", Map.of("aiService", aiService)));
    }
}
