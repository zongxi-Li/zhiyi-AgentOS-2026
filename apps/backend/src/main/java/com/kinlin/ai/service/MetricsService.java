package com.kinlin.ai.service;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.TimeUnit;

/**
 * 指标服务
 * 收集和记录系统性能指标
 */
@Service
@RequiredArgsConstructor
public class MetricsService {

    private final MeterRegistry meterRegistry;

    /**
     * 记录API请求
     */
    public void recordApiRequest(String endpoint, String method) {
        Counter.builder("api.requests")
                .tag("endpoint", endpoint)
                .tag("method", method)
                .register(meterRegistry)
                .increment();
    }

    /**
     * 记录API响应时间
     */
    public void recordApiResponseTime(String endpoint, long duration, TimeUnit unit) {
        Timer.builder("api.response.time")
                .tag("endpoint", endpoint)
                .register(meterRegistry)
                .record(duration, unit);
    }

    /**
     * 记录错误
     */
    public void recordError(String errorType) {
        Counter.builder("api.errors")
                .tag("type", errorType)
                .register(meterRegistry)
                .increment();
    }

    /**
     * 记录对话消息数
     */
    public void recordMessageCount() {
        Counter.builder("chat.messages")
                .register(meterRegistry)
                .increment();
    }

    /**
     * 记录角色切换
     */
    public void recordRoleSwitch() {
        Counter.builder("roles.switches")
                .register(meterRegistry)
                .increment();
    }

    /**
     * 获取指标数据（用于告警检查）
     */
    public Map<String, Object> getMetrics() {
        Map<String, Object> metrics = new HashMap<>();
        
        try {
            // 获取请求总数
            Counter totalRequestsCounter = meterRegistry.find("api.requests").counter();
            double totalRequests = totalRequestsCounter != null ? totalRequestsCounter.count() : 0.0;
            metrics.put("totalRequests", (long) totalRequests);

            // 获取错误数
            Counter errorCountCounter = meterRegistry.find("api.errors").counter();
            double errorCount = errorCountCounter != null ? errorCountCounter.count() : 0.0;
            metrics.put("errorCount", (long) errorCount);

            // 获取平均响应时间（毫秒）
            Timer responseTimeTimer = meterRegistry.find("api.response.time").timer();
            double avgResponseTime = responseTimeTimer != null 
                ? responseTimeTimer.mean(TimeUnit.MILLISECONDS) 
                : 0.0;
            metrics.put("avgResponseTime", avgResponseTime);

            // 计算每分钟请求数（简化实现）
            long requestsPerMinute = (long) (totalRequests / 60.0);
            metrics.put("requestsPerMinute", requestsPerMinute);

        } catch (Exception e) {
            // 如果获取指标失败，返回默认值
            metrics.put("totalRequests", 0L);
            metrics.put("errorCount", 0L);
            metrics.put("avgResponseTime", 0.0);
            metrics.put("requestsPerMinute", 0L);
        }

        return metrics;
    }
}

