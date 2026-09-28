package com.kinlin.ai.infrastructure.http;

import com.kinlin.ai.client.RoleFusionClient;
import com.kinlin.ai.dto.RoleFusionRequest;
import org.springframework.stereotype.Component;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * WebClient implementation of the role-fusion capability
 * ({@code /ai/role-fusion/**} family). Unwraps the upstream {@code success/data}
 * envelope; fusion payloads stay dynamic maps.
 */
@Component
public class WebClientRoleFusionClient implements RoleFusionClient {

    private final PlatformAiTransport transport;

    public WebClientRoleFusionClient(PlatformAiTransport transport) {
        this.transport = transport;
    }

    @Override
    public Map<String, Object> fuseRoles(RoleFusionRequest request) {
        Map<String, Object> requestBody = new HashMap<>();
        requestBody.put("question", request.getQuestion());
        requestBody.put("available_roles", toRoleMaps(request.getAvailableRoles()));
        requestBody.put("role_responses", request.getRoleResponses());

        return unwrap(transport.postJson("/ai/role-fusion/fuse", requestBody, TransportTypes.MAP));
    }

    @Override
    public Map<String, Object> calculateRoleWeights(String question, List<RoleFusionRequest.RoleInfo> availableRoles) {
        Map<String, Object> requestBody = new HashMap<>();
        requestBody.put("question", question);
        requestBody.put("available_roles", toRoleMaps(availableRoles));

        return unwrap(transport.postJson("/ai/role-fusion/weights", requestBody, TransportTypes.MAP));
    }

    private static List<Map<String, Object>> toRoleMaps(List<RoleFusionRequest.RoleInfo> availableRoles) {
        return availableRoles.stream()
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
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> unwrap(Map<String, Object> responseMap) {
        if (responseMap != null && Boolean.TRUE.equals(responseMap.get("success"))) {
            return (Map<String, Object>) responseMap.get("data");
        }
        return new HashMap<>();
    }
}
