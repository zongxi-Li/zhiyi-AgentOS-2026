package com.kinlin.ai.controller;

import com.kinlin.ai.service.StatisticsService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.Map;
import java.util.UUID;

/**
 * 统计控制器
 */
@RestController
@RequestMapping("/statistics")
@RequiredArgsConstructor
public class StatisticsController {

    private final StatisticsService statisticsService;

    /**
     * 获取用户统计
     */
    @GetMapping("/user/{userId}")
    public ResponseEntity<Map<String, Object>> getUserStatistics(@PathVariable UUID userId) {
        Map<String, Object> stats = statisticsService.getUserStatistics(userId);
        return ResponseEntity.ok(stats);
    }

    /**
     * 获取系统统计
     */
    @GetMapping("/system")
    public ResponseEntity<Map<String, Object>> getSystemStatistics() {
        Map<String, Object> stats = statisticsService.getSystemStatistics();
        return ResponseEntity.ok(stats);
    }

    /**
     * 获取角色使用统计
     */
    @GetMapping("/user/{userId}/roles")
    public ResponseEntity<Map<String, Object>> getRoleStatistics(@PathVariable UUID userId) {
        Map<String, Object> stats = statisticsService.getRoleStatistics(userId);
        return ResponseEntity.ok(stats);
    }
}

