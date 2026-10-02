package com.kinlin.ai.projection.workspace.dto;

import java.util.List;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/**
 * Typed Mission Workspace envelope over the upstream MissionWorkspaceProjection wire
 * (runtime/v2/workspace.py, dumped with by_alias/mode=json/exclude_none).
 *
 * <p>Upstream serializes {@code exclude_none}, so every null model field is absent on the
 * wire; the same NON_NULL rule applies here. Plain dict values (entry metadata, activeGraph)
 * keep nested nulls upstream — this projection normalizes them to absent fields, which every
 * verified frontend reader ({@code ?.}, {@code ||}, {@code ??}, {@code == null}) treats
 * identically. E1 defines the contracts only; the controller still passes the raw wire.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record MissionWorkspaceQuery(
        WorkspaceMissionQuery mission,
        WorkspaceRunSummaryQuery activeRun,
        WorkspaceGraphQuery activeGraph,
        List<WorkspaceRunSummaryQuery> runs,
        List<WorkspaceEntryQuery> entries,
        List<WorkspaceGraphNodeQuery> graphNodes,
        List<WorkspaceAttachmentQuery> inputAttachments,
        List<WorkspaceDiagnosticQuery> diagnostics
) implements QueryResponse {
    public MissionWorkspaceQuery {
        runs = List.copyOf(runs);
        entries = List.copyOf(entries);
        graphNodes = List.copyOf(graphNodes);
        inputAttachments = List.copyOf(inputAttachments);
        diagnostics = List.copyOf(diagnostics);
    }
}
