package com.kinlin.ai.projection.workspace.mapper;
import java.util.Map;
import com.kinlin.ai.projection.workspace.dto.*;
import static com.kinlin.ai.projection.common.mapper.QueryWire.*;

/** Explicit public file/authorization projections; no platform entity or arbitrary map escapes. */
public final class WorkspaceFilesProjectionMapper {
    private WorkspaceFilesProjectionMapper() { }
    public static WorkspaceToolApprovalsQuery approvals(Map<String, Object> source) {
        return new WorkspaceToolApprovalsQuery(items(source.get("items"), item -> new WorkspaceToolApprovalsQuery.Approval(
            text(item,"approvalId"),text(item,"toolCallId"),text(item,"invocationId"),text(item,"toolName"),
            text(item,"capabilityId"),text(item,"relativePath"),text(item,"operationSummary"),text(item,"createdAt"),
            text(item,"status"),text(item,"sessionId"),text(item,"operation"),text(item,"command"),text(item,"cwd"),text(item,"riskNotice"))));
    }
    public static WorkspaceFileListingQuery listing(Map<String, Object> source) {
        return new WorkspaceFileListingQuery(text(source,"workspaceRoot"), text(source,"path"), items(source.get("entries"), value -> {
            var item=object(value);
            return new WorkspaceFileListingQuery.Entry(text(item,"name"), text(item,"path"), text(item,"type"));
        }));
    }
    public static WorkspaceFileContentQuery content(Map<String, Object> source) {
        return new WorkspaceFileContentQuery(text(source,"workspaceRoot"),text(source,"path"),text(source,"content"),text(source,"version"));
    }
    public static WorkspaceAuthorizationQuery authorization(Map<?, ?> source) {
        return new WorkspaceAuthorizationQuery(text(source,"workspaceRoot"),text(source,"workspaceId"),text(source,"grantId"),
            text(source,"resourceId"),text(source,"rootIdentity"),bool(source,"revoked"),bool(source,"selected"),
            text(source,"scope"),text(source,"confinement"),text(source,"risk"));
    }
    public static WorkspaceAuthorizationsQuery authorizations(Map<String, Object> source) {
        return new WorkspaceAuthorizationsQuery(items(source.get("workspaces"), value -> authorization(object(value))));
    }
}
