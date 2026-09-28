package com.kinlin.ai.service;

import com.kinlin.ai.client.PlatformAiClientException;
import com.kinlin.ai.client.RoleFusionClient;
import com.kinlin.ai.dto.RoleFusionRequest;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 角色融合应用服务：角色融合能力的业务编排与 fallback 决策。
 *
 * <p>HTTP 细节与 {@code success/data} 信封解包已下沉到 {@link RoleFusionClient}；
 * transport 失败时保持既有用户可见行为（error Map）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class RoleFusionService {

    private final RoleFusionClient roleFusionClient;

    /**
     * 融合多个角色的回答
     */
    public Map<String, Object> fuseRoles(RoleFusionRequest request) {
        try {
            return roleFusionClient.fuseRoles(request);
        } catch (PlatformAiClientException e) {
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
            return roleFusionClient.calculateRoleWeights(question, availableRoles);
        } catch (PlatformAiClientException e) {
            log.error("计算角色权重失败", e);
            Map<String, Object> errorResponse = new HashMap<>();
            errorResponse.put("error", "计算角色权重失败: " + e.getMessage());
            return errorResponse;
        }
    }
}
