package com.kinlin.ai.controller;

import com.kinlin.ai.service.AlertService;
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
    public ResponseEntity<Map<String, List<AlertService.Alert>>> getAlertHistory() {
        Map<String, List<AlertService.Alert>> alerts = alertService.getAllAlerts();
        return ResponseEntity.ok(alerts);
    }

    /**
     * 获取指定类型的告警
     */
    @GetMapping("/history/{alertType}")
    public ResponseEntity<List<AlertService.Alert>> getAlertHistoryByType(
            @PathVariable String alertType
    ) {
        List<AlertService.Alert> alerts = alertService.getAlertHistory(alertType);
        return ResponseEntity.ok(alerts);
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

