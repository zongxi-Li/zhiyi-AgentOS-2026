package com.kinlin.ai.aspect;

import com.kinlin.ai.service.MetricsService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.springframework.stereotype.Component;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import jakarta.servlet.http.HttpServletRequest;
import java.util.concurrent.TimeUnit;

/**
 * 指标收集切面
 * 自动收集API调用指标
 */
@Slf4j
@Aspect
@Component
@RequiredArgsConstructor
public class MetricsAspect {

    private final MetricsService metricsService;

    @Around("@within(org.springframework.web.bind.annotation.RestController)")
    public Object collectMetrics(ProceedingJoinPoint joinPoint) throws Throwable {
        long startTime = System.currentTimeMillis();
        
        try {
            // 记录请求
            HttpServletRequest request = ((ServletRequestAttributes) 
                    RequestContextHolder.currentRequestAttributes()).getRequest();
            String endpoint = request.getRequestURI();
            String method = request.getMethod();
            
            metricsService.recordApiRequest(endpoint, method);
            
            // 执行方法
            Object result = joinPoint.proceed();
            
            // 记录响应时间
            long duration = System.currentTimeMillis() - startTime;
            metricsService.recordApiResponseTime(endpoint, duration, TimeUnit.MILLISECONDS);
            
            return result;
        } catch (Exception e) {
            // 记录错误
            metricsService.recordError(e.getClass().getSimpleName());
            throw e;
        }
    }
}

