package com.kinlin.ai.service;

import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.util.HashMap;
import java.util.Map;

/**
 * 银河麒麟系统集成服务
 * 实现系统服务集成、安全机制集成、资源监控等功能
 */
@Slf4j
@Service
public class KylinOSIntegrationService {

    /**
     * 检测是否为银河麒麟系统
     */
    public boolean isKylinOS() {
        try {
            // 检查系统信息
            String osName = System.getProperty("os.name", "").toLowerCase();
            if (osName.contains("kylin") || osName.contains("neokylin")) {
                return true;
            }
            
            // 检查发行版文件
            Process process = Runtime.getRuntime().exec("cat /etc/kylin-release");
            try (BufferedReader reader = new BufferedReader(
                    new InputStreamReader(process.getInputStream()))) {
                String line = reader.readLine();
                if (line != null && !line.isEmpty()) {
                    return true;
                }
            }
        } catch (Exception e) {
            log.debug("检测操作系统失败: {}", e.getMessage());
        }
        return false;
    }

    /**
     * 获取系统信息
     */
    public Map<String, Object> getSystemInfo() {
        Map<String, Object> info = new HashMap<>();
        
        info.put("osName", System.getProperty("os.name"));
        info.put("osVersion", System.getProperty("os.version"));
        info.put("osArch", System.getProperty("os.arch"));
        info.put("javaVersion", System.getProperty("java.version"));
        info.put("isKylinOS", isKylinOS());
        
        if (isKylinOS()) {
            try {
                info.put("kylinVersion", getKylinVersion());
            } catch (Exception e) {
                log.warn("获取银河麒麟版本失败: {}", e.getMessage());
            }
        }
        
        return info;
    }

    /**
     * 获取银河麒麟版本
     */
    private String getKylinVersion() {
        try {
            Process process = Runtime.getRuntime().exec("cat /etc/kylin-release");
            try (BufferedReader reader = new BufferedReader(
                    new InputStreamReader(process.getInputStream()))) {
                return reader.readLine();
            }
        } catch (Exception e) {
            log.warn("读取银河麒麟版本失败: {}", e.getMessage());
            return "unknown";
        }
    }

    /**
     * 监控系统资源
     */
    public Map<String, Object> monitorSystemResources() {
        Map<String, Object> resources = new HashMap<>();
        
        Runtime runtime = Runtime.getRuntime();
        
        // CPU信息
        Map<String, Object> cpu = new HashMap<>();
        cpu.put("processors", Runtime.getRuntime().availableProcessors());
        resources.put("cpu", cpu);
        
        // 内存信息
        Map<String, Object> memory = new HashMap<>();
        long totalMemory = runtime.totalMemory();
        long freeMemory = runtime.freeMemory();
        long usedMemory = totalMemory - freeMemory;
        
        memory.put("total", totalMemory);
        memory.put("used", usedMemory);
        memory.put("free", freeMemory);
        memory.put("percent", (double) usedMemory / totalMemory * 100);
        resources.put("memory", memory);
        
        // 如果是银河麒麟系统，添加系统服务状态
        if (isKylinOS()) {
            resources.put("systemServices", getSystemServicesStatus());
        }
        
        return resources;
    }

    /**
     * 获取系统服务状态
     */
    private Map<String, String> getSystemServicesStatus() {
        Map<String, String> services = new HashMap<>();
        
        String[] serviceNames = {"NetworkManager", "firewalld", "kylin-security"};
        
        for (String serviceName : serviceNames) {
            try {
                Process process = Runtime.getRuntime().exec(
                    new String[]{"systemctl", "is-active", serviceName}
                );
                try (BufferedReader reader = new BufferedReader(
                        new InputStreamReader(process.getInputStream()))) {
                    String status = reader.readLine();
                    services.put(serviceName, status != null ? status : "unknown");
                }
            } catch (Exception e) {
                services.put(serviceName, "unknown");
            }
        }
        
        return services;
    }

    /**
     * 获取安全状态
     */
    public Map<String, Object> getSecurityStatus() {
        if (!isKylinOS()) {
            Map<String, Object> result = new HashMap<>();
            result.put("error", "非银河麒麟系统");
            return result;
        }
        
        Map<String, Object> security = new HashMap<>();
        
        try {
            // 检查防火墙状态
            security.put("firewallStatus", checkServiceStatus("firewalld"));
            
            // 检查SELinux状态
            security.put("selinuxStatus", getSELinuxStatus());
        } catch (Exception e) {
            log.error("获取安全状态失败: {}", e.getMessage());
            security.put("error", e.getMessage());
        }
        
        return security;
    }

    /**
     * 检查服务状态
     */
    private String checkServiceStatus(String serviceName) {
        try {
            Process process = Runtime.getRuntime().exec(
                new String[]{"systemctl", "is-active", serviceName}
            );
            try (BufferedReader reader = new BufferedReader(
                    new InputStreamReader(process.getInputStream()))) {
                return reader.readLine();
            }
        } catch (Exception e) {
            return "unknown";
        }
    }

    /**
     * 获取SELinux状态
     */
    private String getSELinuxStatus() {
        try {
            Process process = Runtime.getRuntime().exec("getenforce");
            try (BufferedReader reader = new BufferedReader(
                    new InputStreamReader(process.getInputStream()))) {
                return reader.readLine();
            }
        } catch (Exception e) {
            return "unknown";
        }
    }
}





