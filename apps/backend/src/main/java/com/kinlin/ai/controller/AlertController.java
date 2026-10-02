package com.kinlin.ai.controller;

import com.kinlin.ai.service.AlertService;
import com.kinlin.ai.projection.operational.dto.OperationalQuery;
import com.kinlin.ai.projection.operational.mapper.OperationalProjectionMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * 告警控制器
 */
@RestController
@RequestMapping("/api/alerts")
@RequiredArgsConstructor
public class AlertController {

    private final AlertService alertService;

    /**
     * 手动触发告警检查
     */
    @PostMapping("/check")
    public ResponseEntity<Map<String, String>> checkAlerts() {
        alertService.checkSystemStatus();
        return ResponseEntity.ok(Map.of("message", "告警检查已完成"));
    }

    /**
     * 获取告警历史
     */
    @GetMapping("/history")
    public ResponseEntity<List<OperationalQuery.AlertGroup>> getAlertHistory() {
        Map<String, List<AlertService.Alert>> alerts = alertService.getAllAlerts();
        return ResponseEntity.ok(alerts.entrySet().stream().map(entry -> OperationalProjectionMapper.alertGroup(
                entry.getKey(), projectAlerts(entry.getValue()))).toList());
    }

    /**
     * 获取指定类型的告警
     */
    @GetMapping("/history/{alertType}")
    public ResponseEntity<List<OperationalQuery.Alert>> getAlertHistoryByType(
            @PathVariable String alertType
    ) {
        List<AlertService.Alert> alerts = alertService.getAlertHistory(alertType);
        return ResponseEntity.ok(projectAlerts(alerts));
    }

    private static List<OperationalQuery.Alert> projectAlerts(List<AlertService.Alert> alerts) {
        return alerts.stream().map(item -> OperationalProjectionMapper.alert(item.getAlertType(), item.getMessage(),
                item.getSeverity(), item.getTimestamp())).toList();
    }

    /**
     * 手动触发告警（用于测试）
     */
    @PostMapping("/trigger")
    public ResponseEntity<Map<String, String>> triggerAlert(
            @RequestBody Map<String, String> request
    ) {
        String alertType = request.get("alertType");
        String message = request.get("message");
        String severity = request.getOrDefault("severity", "info");

        alertService.triggerAlert(alertType, message, severity);
        return ResponseEntity.ok(Map.of("message", "告警已触发"));
    }
}

