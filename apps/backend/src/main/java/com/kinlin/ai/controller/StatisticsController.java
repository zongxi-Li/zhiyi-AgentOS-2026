package com.kinlin.ai.controller;

import com.kinlin.ai.exception.ResourceNotFoundException;
import com.kinlin.ai.security.AuthenticatedUser;
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
     * 获取用户统计（路径参数仅为兼容保留，实际以认证身份为准）
     */
    @GetMapping("/user/{userId}")
    public ResponseEntity<Map<String, Object>> getUserStatistics(@PathVariable UUID userId) {
        UUID currentUserId = requireCurrentUserId();
        Map<String, Object> stats = statisticsService.getUserStatistics(currentUserId);
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
     * 获取角色使用统计（路径参数仅为兼容保留，实际以认证身份为准）
     */
    @GetMapping("/user/{userId}/roles")
    public ResponseEntity<Map<String, Object>> getRoleStatistics(@PathVariable UUID userId) {
        UUID currentUserId = requireCurrentUserId();
        Map<String, Object> stats = statisticsService.getRoleStatistics(currentUserId);
        return ResponseEntity.ok(stats);
    }

    private UUID requireCurrentUserId() {
        return AuthenticatedUser.currentUserId()
                .orElseThrow(() -> new ResourceNotFoundException("未认证，无法获取用户统计"));
    }
}

