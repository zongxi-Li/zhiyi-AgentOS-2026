package com.kinlin.ai.projection.workspace.dto;
import java.util.List;
import com.kinlin.ai.projection.common.dto.QueryResponse;
public record WorkspaceToolApprovalsQuery(List<Approval> items) implements QueryResponse {
    public record Approval(String approvalId, String toolCallId, String invocationId, String toolName,
        String capabilityId, String relativePath, String operationSummary, String createdAt,
        String status, String sessionId, String operation, String command, String cwd, String riskNotice) { }
}
