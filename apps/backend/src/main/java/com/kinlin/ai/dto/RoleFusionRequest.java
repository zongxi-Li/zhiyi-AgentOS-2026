package com.kinlin.ai.dto;

import lombok.Data;
import java.util.List;
import java.util.Map;

/**
 * 角色融合请求DTO
 */
@Data
public class RoleFusionRequest {
    private String question;
    private List<RoleInfo> availableRoles;
    private Map<String, String> roleResponses; // {role_id: response}
    
    @Data
    public static class RoleInfo {
        private String roleId;
        private List<String> knowledgeDomain;
        private String personality;
    }
}

