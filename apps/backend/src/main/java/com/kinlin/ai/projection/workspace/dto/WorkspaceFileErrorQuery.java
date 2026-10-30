package com.kinlin.ai.projection.workspace.dto;
import com.kinlin.ai.projection.common.dto.QueryResponse;
/** Legacy file endpoint detail, retained without exposing arbitrary upstream fields. */
public record WorkspaceFileErrorQuery(String detail) implements QueryResponse { }
