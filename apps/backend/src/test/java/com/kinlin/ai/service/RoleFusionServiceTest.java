package com.kinlin.ai.service;

import com.kinlin.ai.client.PlatformAiClientException;
import com.kinlin.ai.client.RoleFusionClient;
import com.kinlin.ai.dto.RoleFusionRequest;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.when;

/**
 * RoleFusionService单元测试（应用层 fallback 表征：transport 失败时的既有用户可见行为）
 */
@ExtendWith(MockitoExtension.class)
class RoleFusionServiceTest {

    @Mock
    private RoleFusionClient roleFusionClient;

    private RoleFusionService roleFusionService;

    @BeforeEach
    void setUp() {
        roleFusionService = new RoleFusionService(roleFusionClient);
    }

    @Test
    void testFuseRoles_Success() {
        // Arrange
        RoleFusionRequest request = buildFusionRequest();

        when(roleFusionClient.fuseRoles(request)).thenReturn(Map.of("fused_response", "综合建议..."));

        // Act
        Map<String, Object> result = roleFusionService.fuseRoles(request);

        // Assert
        assertNotNull(result);
        assertEquals("综合建议...", result.get("fused_response"));
    }

    @Test
    void testCalculateRoleWeights_Success() {
        // Arrange
        String question = "我想创业";
        List<RoleFusionRequest.RoleInfo> roles = List.of(roleInfo("lawyer", Arrays.asList("法律")));

        when(roleFusionClient.calculateRoleWeights(question, roles))
                .thenReturn(Map.of("weights", Map.of("lawyer", 0.8)));

        // Act
        Map<String, Object> result = roleFusionService.calculateRoleWeights(question, roles);

        // Assert
        assertNotNull(result);
        @SuppressWarnings("unchecked")
        Map<String, Double> weights = (Map<String, Double>) result.get("weights");
        assertEquals(0.8, weights.get("lawyer"));
    }

    @Test
    void testFuseRoles_TransportFailureKeepsFrozenErrorMap() {
        // Arrange：表征冻结——error Map 携带既有前缀文案
        RoleFusionRequest request = buildFusionRequest();
        when(roleFusionClient.fuseRoles(request))
                .thenThrow(new PlatformAiClientException(
                        PlatformAiClientException.Type.TIMEOUT, "Did not observe any item"));

        // Act
        Map<String, Object> result = roleFusionService.fuseRoles(request);

        // Assert
        assertEquals("角色融合失败: Did not observe any item", result.get("error"));
    }

    @Test
    void testCalculateRoleWeights_TransportFailureKeepsFrozenErrorMap() {
        // Arrange
        when(roleFusionClient.calculateRoleWeights(org.mockito.ArgumentMatchers.anyString(), org.mockito.ArgumentMatchers.anyList()))
                .thenThrow(new PlatformAiClientException(
                        PlatformAiClientException.Type.UNAVAILABLE, "Connection refused"));

        // Act
        Map<String, Object> result = roleFusionService.calculateRoleWeights(
                "我想创业", new ArrayList<>());

        // Assert
        assertEquals("计算角色权重失败: Connection refused", result.get("error"));
    }

    private static RoleFusionRequest buildFusionRequest() {
        RoleFusionRequest request = new RoleFusionRequest();
        request.setQuestion("我想创业");
        request.setAvailableRoles(Arrays.asList(
                roleInfo("lawyer", Arrays.asList("法律", "合同")),
                roleInfo("business", Arrays.asList("商业", "策略"))
        ));
        request.setRoleResponses(Map.of(
                "lawyer", "法律建议...",
                "business", "商业建议..."
        ));
        return request;
    }

    private static RoleFusionRequest.RoleInfo roleInfo(String roleId, List<String> domains) {
        RoleFusionRequest.RoleInfo info = new RoleFusionRequest.RoleInfo();
        info.setRoleId(roleId);
        info.setKnowledgeDomain(domains);
        return info;
    }
}
