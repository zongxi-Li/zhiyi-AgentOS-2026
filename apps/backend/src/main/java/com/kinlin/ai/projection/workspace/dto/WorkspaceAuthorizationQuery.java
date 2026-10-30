package com.kinlin.ai.projection.workspace.dto;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;
@JsonInclude(JsonInclude.Include.NON_NULL)
public record WorkspaceAuthorizationQuery(String workspaceRoot, String workspaceId, String grantId,
    String resourceId, String rootIdentity, Boolean revoked, Boolean selected, String scope,
    String confinement, String risk) implements QueryResponse { }
