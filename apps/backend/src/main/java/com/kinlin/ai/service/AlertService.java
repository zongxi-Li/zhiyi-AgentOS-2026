package com.kinlin.ai.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 告警服务
 * 监控系统异常和性能指标，触发告警
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class AlertService {

    private final MetricsService metricsService;
    
    // 告警规则配置
    private static final double ERROR_RATE_THRESHOLD = 0.1; // 10%错误率
    private static final long RESPONSE_TIME_THRESHOLD_MS = 5000; // 5秒响应时间
    private static final long REQUEST_RATE_THRESHOLD = 1000; // 每秒1000请求

    // 告警历史（实际应使用数据库存储）
    private final Map<String, List<Alert>> alertHistory = new ConcurrentHashMap<>();

    /**
     * 检查系统状态并触发告警
     */
    public void checkSystemStatus() {
        try {
            // 检查错误率
            checkErrorRate();
            
            // 检查响应时间
            checkResponseTime();
            
            // 检查请求速率
            checkRequestRate();
            
        } catch (Exception e) {
            log.error("告警检查失败", e);
        }
    }

    /**
     * 检查错误率
     */
    private void checkErrorRate() {
        try {
            Map<String, Object> metrics = metricsService.getMetrics();
            Long totalRequests = (Long) metrics.getOrDefault("totalRequests", 0L);
            Long errorCount = (Long) metrics.getOrDefault("errorCount", 0L);
            
            if (totalRequests > 0) {
                double errorRate = (double) errorCount / totalRequests;
                if (errorRate > ERROR_RATE_THRESHOLD) {
                    triggerAlert("ERROR_RATE", 
                            String.format("错误率过高: %.2f%% (阈值: %.2f%%)", 
                                    errorRate * 100, ERROR_RATE_THRESHOLD * 100),
                            "warning");
                }
            }
        } catch (Exception e) {
            log.error("检查错误率失败", e);
        }
    }

    /**
     * 检查响应时间
     */
    private void checkResponseTime() {
        try {
            Map<String, Object> metrics = metricsService.getMetrics();
            Double avgResponseTime = (Double) metrics.getOrDefault("avgResponseTime", 0.0);
            
            if (avgResponseTime > RESPONSE_TIME_THRESHOLD_MS) {
                triggerAlert("RESPONSE_TIME",
                        String.format("平均响应时间过长: %.2fms (阈值: %dms)",
                                avgResponseTime, RESPONSE_TIME_THRESHOLD_MS),
                        "warning");
            }
        } catch (Exception e) {
            log.error("检查响应时间失败", e);
        }
    }

    /**
     * 检查请求速率
     */
    private void checkRequestRate() {
        try {
            Map<String, Object> metrics = metricsService.getMetrics();
            Long requestsPerMinute = (Long) metrics.getOrDefault("requestsPerMinute", 0L);
            
            if (requestsPerMinute > REQUEST_RATE_THRESHOLD * 60) {
                triggerAlert("REQUEST_RATE",
                        String.format("请求速率过高: %d/分钟 (阈值: %d/分钟)",
                                requestsPerMinute, REQUEST_RATE_THRESHOLD * 60),
                        "info");
            }
        } catch (Exception e) {
            log.error("检查请求速率失败", e);
        }
    }

    /**
     * 触发告警
     */
    public void triggerAlert(String alertType, String message, String severity) {
        Alert alert = new Alert();
        alert.setAlertType(alertType);
        alert.setMessage(message);
        alert.setSeverity(severity);
        alert.setTimestamp(LocalDateTime.now());

        // 记录告警
        alertHistory.computeIfAbsent(alertType, k -> new ArrayList<>()).add(alert);
        
        // 限制历史记录数量
        List<Alert> alerts = alertHistory.get(alertType);
        if (alerts.size() > 100) {
            alerts.remove(0);
        }

        // 记录日志
        switch (severity) {
            case "critical":
                log.error("[告警] {}: {}", alertType, message);
                break;
            case "warning":
                log.warn("[告警] {}: {}", alertType, message);
                break;
            default:
                log.info("[告警] {}: {}", alertType, message);
        }
    }

    /**
     * 获取告警历史
     */
    public List<Alert> getAlertHistory(String alertType) {
        return alertHistory.getOrDefault(alertType, new ArrayList<>());
    }

    /**
     * 获取所有告警
     */
    public Map<String, List<Alert>> getAllAlerts() {
        return new HashMap<>(alertHistory);
    }

    /**
     * 告警数据类
     */
    public static class Alert {
        private String alertType;
        private String message;
        private String severity; // critical, warning, info
        private LocalDateTime timestamp;

        // Getters and Setters
        public String getAlertType() {
            return alertType;
        }

        public void setAlertType(String alertType) {
            this.alertType = alertType;
        }

        public String getMessage() {
            return message;
        }

        public void setMessage(String message) {
            this.message = message;
        }

        public String getSeverity() {
            return severity;
        }

        public void setSeverity(String severity) {
            this.severity = severity;
        }

        public LocalDateTime getTimestamp() {
            return timestamp;
        }

        public void setTimestamp(LocalDateTime timestamp) {
            this.timestamp = timestamp;
        }
    }
}

