package com.kinlin.ai.projection.workspace.dto;
import com.kinlin.ai.projection.common.dto.QueryResponse;
import java.util.List;
public record WorkspaceFileListingQuery(String workspaceRoot, String path, List<Entry> entries) implements QueryResponse {
    public record Entry(String name, String path, String type) { }
}
