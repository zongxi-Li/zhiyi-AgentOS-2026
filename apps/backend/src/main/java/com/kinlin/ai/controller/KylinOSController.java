package com.kinlin.ai.controller;

import com.kinlin.ai.service.KylinOSIntegrationService;
import com.kinlin.ai.projection.operational.dto.OperationalQuery;
import com.kinlin.ai.projection.operational.mapper.OperationalProjectionMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

/**
 * 银河麒麟系统集成控制器
 */
@RestController
@RequestMapping("/api/kylin-os")
@RequiredArgsConstructor
public class KylinOSController {

    private final KylinOSIntegrationService kylinOSService;

    /**
     * 获取系统信息
     */
    @GetMapping("/system-info")
    public ResponseEntity<OperationalQuery.SystemInfo> getSystemInfo() {
        Map<String, Object> info = kylinOSService.getSystemInfo();
        return ResponseEntity.ok(OperationalProjectionMapper.systemInfo(info));
    }

    /**
     * 监控系统资源
     */
    @GetMapping("/resources")
    public ResponseEntity<OperationalQuery.Resources> monitorResources() {
        Map<String, Object> resources = kylinOSService.monitorSystemResources();
        return ResponseEntity.ok(OperationalProjectionMapper.resources(resources));
    }

    /**
     * 获取安全状态
     */
    @GetMapping("/security")
    public ResponseEntity<OperationalQuery.Security> getSecurityStatus() {
        Map<String, Object> security = kylinOSService.getSecurityStatus();
        return ResponseEntity.ok(OperationalProjectionMapper.security(security));
    }
}





