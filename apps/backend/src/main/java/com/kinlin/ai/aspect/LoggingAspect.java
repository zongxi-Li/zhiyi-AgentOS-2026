package com.kinlin.ai.aspect;

import com.kinlin.ai.annotation.LogExecutionTime;
import lombok.extern.slf4j.Slf4j;
import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.springframework.stereotype.Component;

/**
 * 日志切面
 * 记录方法执行时间
 */
@Slf4j
@Aspect
@Component
public class LoggingAspect {

    @Around("@annotation(logExecutionTime)")
    public Object logExecutionTime(ProceedingJoinPoint joinPoint, LogExecutionTime logExecutionTime) throws Throwable {
        long start = System.currentTimeMillis();
        
        Object proceed = joinPoint.proceed();
        
        long executionTime = System.currentTimeMillis() - start;
        String methodName = joinPoint.getSignature().toShortString();
        String message = logExecutionTime.value().isEmpty() 
            ? methodName 
            : logExecutionTime.value();
        
        log.info("{} 执行时间: {}ms", message, executionTime);
        
        return proceed;
    }
}

