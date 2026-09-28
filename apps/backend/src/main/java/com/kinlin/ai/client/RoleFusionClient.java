package com.kinlin.ai.client;

import com.kinlin.ai.dto.RoleFusionRequest;

import java.util.List;
import java.util.Map;

/**
 * What the Java platform needs from the Python role-fusion capability
 * ({@code /ai/role-fusion/**} family). Fusion payloads stay dynamic {@code Map}
 * projections; the {@code success/data} envelope is unwrapped here.
 */
public interface RoleFusionClient {

    Map<String, Object> fuseRoles(RoleFusionRequest request);

    Map<String, Object> calculateRoleWeights(String question, List<RoleFusionRequest.RoleInfo> availableRoles);
}
