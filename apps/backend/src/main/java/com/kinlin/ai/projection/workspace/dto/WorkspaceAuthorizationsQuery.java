package com.kinlin.ai.projection.workspace.dto;
import com.kinlin.ai.projection.common.dto.QueryResponse;
import java.util.List;
public record WorkspaceAuthorizationsQuery(List<WorkspaceAuthorizationQuery> workspaces) implements QueryResponse { }
