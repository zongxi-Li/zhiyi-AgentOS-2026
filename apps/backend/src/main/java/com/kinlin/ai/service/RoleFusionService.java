package com.kinlin.ai.service;

import com.kinlin.ai.dto.RoleFusionRequest;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.time.Duration;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 角色融合服务
 * 负责与Python AI服务的角色融合功能通信
 */
@Slf4j
@Service
public class RoleFusionService {

    private final WebClient webClient;

    @Value("${ai.service.url}")
    private String aiServiceUrl;

    @Value("${ai.service.timeout}")
    private int timeout;

    public RoleFusionService(WebClient.Builder webClientBuilder, 
                            @Value("${ai.service.url}") String aiServiceUrl, 
                            @Value("${ai.service.timeout}") int timeout) {
        this.aiServiceUrl = aiServiceUrl;
        this.timeout = timeout;
        this.webClient = webClientBuilder
                .baseUrl(aiServiceUrl)
                .build();
    }

    /**
     * 融合多个角色的回答
     */
    public Map<String, Object> fuseRoles(RoleFusionRequest request) {
        try {
            Map<String, Object> requestBody = new HashMap<>();
            requestBody.put("question", request.getQuestion());
            
            // 转换角色信息
            List<Map<String, Object>> roles = request.getAvailableRoles().stream()
                    .map(roleInfo -> {
                        Map<String, Object> role = new HashMap<>();
                        role.put("role_id", roleInfo.getRoleId());
                        role.put("knowledge_domain", roleInfo.getKnowledgeDomain());
                        if (roleInfo.getPersonality() != null) {
                            role.put("personality", roleInfo.getPersonality());
                        }
                        return role;
                    })
                    .collect(Collectors.toList());
            requestBody.put("available_roles", roles);
            requestBody.put("role_responses", request.getRoleResponses());

            Map<String, Object> responseMap = webClient.post()
                    .uri("/ai/role-fusion/fuse")
                    .bodyValue(requestBody)
                    .retrieve()
                    .bodyToMono(Map.class)
                    .timeout(Duration.ofMillis(timeout))
                    .block();

            if (responseMap != null && Boolean.TRUE.equals(responseMap.get("success"))) {
                return (Map<String, Object>) responseMap.get("data");
            }
            return new HashMap<>();
        } catch (Exception e) {
            log.error("角色融合失败", e);
            Map<String, Object> errorResponse = new HashMap<>();
            errorResponse.put("error", "角色融合失败: " + e.getMessage());
            return errorResponse;
        }
    }

    /**
     * 计算角色权重
     */
    public Map<String, Object> calculateRoleWeights(String question, List<RoleFusionRequest.RoleInfo> availableRoles) {
        try {
            Map<String, Object> requestBody = new HashMap<>();
            requestBody.put("question", question);
            
            List<Map<String, Object>> roles = availableRoles.stream()
                    .map(roleInfo -> {
                        Map<String, Object> role = new HashMap<>();
                        role.put("role_id", roleInfo.getRoleId());
                        role.put("knowledge_domain", roleInfo.getKnowledgeDomain());
                        if (roleInfo.getPersonality() != null) {
                            role.put("personality", roleInfo.getPersonality());
                        }
                        return role;
                    })
                    .collect(Collectors.toList());
            requestBody.put("available_roles", roles);

            Map<String, Object> responseMap = webClient.post()
                    .uri("/ai/role-fusion/weights")
                    .bodyValue(requestBody)
                    .retrieve()
                    .bodyToMono(Map.class)
                    .timeout(Duration.ofMillis(timeout))
                    .block();

            if (responseMap != null && Boolean.TRUE.equals(responseMap.get("success"))) {
                return (Map<String, Object>) responseMap.get("data");
            }
            return new HashMap<>();
        } catch (Exception e) {
            log.error("计算角色权重失败", e);
            Map<String, Object> errorResponse = new HashMap<>();
            errorResponse.put("error", "计算角色权重失败: " + e.getMessage());
            return errorResponse;
        }
    }
}

