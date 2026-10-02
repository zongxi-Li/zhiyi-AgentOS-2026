package com.kinlin.ai.controller;

import com.kinlin.ai.exception.ResourceNotFoundException;
import com.kinlin.ai.security.AuthenticatedUser;
import com.kinlin.ai.projection.statistics.dto.RoleStatisticsQuery;
import com.kinlin.ai.projection.statistics.dto.SystemStatisticsQuery;
import com.kinlin.ai.projection.statistics.dto.UserStatisticsQuery;
import com.kinlin.ai.projection.statistics.mapper.StatisticsProjectionMapper;
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
    public ResponseEntity<UserStatisticsQuery> getUserStatistics(@PathVariable UUID userId) {
        UUID currentUserId = requireCurrentUserId();
        return ResponseEntity.ok(
                StatisticsProjectionMapper.userStatistics(statisticsService.getUserStatistics(currentUserId)));
    }

    /**
     * 获取系统统计
     */
    @GetMapping("/system")
    public ResponseEntity<SystemStatisticsQuery> getSystemStatistics() {
        return ResponseEntity.ok(
                StatisticsProjectionMapper.systemStatistics(statisticsService.getSystemStatistics()));
    }

    /**
     * 获取角色使用统计（路径参数仅为兼容保留，实际以认证身份为准）
     */
    @GetMapping("/user/{userId}/roles")
    public ResponseEntity<RoleStatisticsQuery> getRoleStatistics(@PathVariable UUID userId) {
        UUID currentUserId = requireCurrentUserId();
        return ResponseEntity.ok(
                StatisticsProjectionMapper.roleStatistics(statisticsService.getRoleStatistics(currentUserId)));
    }

    private UUID requireCurrentUserId() {
        return AuthenticatedUser.currentUserId()
                .orElseThrow(() -> new ResourceNotFoundException("未认证，无法获取用户统计"));
    }
}

