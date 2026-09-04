package com.kinlin.ai.controller;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.HashMap;
import java.util.Map;

/**
 * 指标监控控制器
 * 提供系统性能指标查询接口
 */
@RestController
@RequestMapping("/metrics")
@RequiredArgsConstructor
public class MetricsController {

    private final MeterRegistry meterRegistry;

    /**
     * 获取系统指标
     */
    @GetMapping
    public ResponseEntity<Map<String, Object>> getMetrics() {
        Map<String, Object> metrics = new HashMap<>();
        
        try {
            // 获取API请求计数
            Counter apiRequestsCounter = meterRegistry.find("api.requests").counter();
            double apiRequests = apiRequestsCounter != null ? apiRequestsCounter.count() : 0.0;
            
            // 获取错误计数
            Counter errorsCounter = meterRegistry.find("api.errors").counter();
            double errors = errorsCounter != null ? errorsCounter.count() : 0.0;
            
            // 获取对话消息数
            Counter messagesCounter = meterRegistry.find("chat.messages").counter();
            double messages = messagesCounter != null ? messagesCounter.count() : 0.0;
            
            metrics.put("apiRequests", apiRequests);
            metrics.put("errors", errors);
            metrics.put("messages", messages);
            metrics.put("errorRate", apiRequests > 0 ? errors / apiRequests : 0);
        } catch (Exception e) {
            // 如果获取指标失败，返回默认值
            metrics.put("apiRequests", 0.0);
            metrics.put("errors", 0.0);
            metrics.put("messages", 0.0);
            metrics.put("errorRate", 0.0);
        }
        
        return ResponseEntity.ok(metrics);
    }
}

