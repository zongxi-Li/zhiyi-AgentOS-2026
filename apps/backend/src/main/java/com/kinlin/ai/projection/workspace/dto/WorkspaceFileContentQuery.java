package com.kinlin.ai.projection.workspace.dto;
import com.kinlin.ai.projection.common.dto.QueryResponse;
public record WorkspaceFileContentQuery(String workspaceRoot, String path, String content, String version) implements QueryResponse { }
