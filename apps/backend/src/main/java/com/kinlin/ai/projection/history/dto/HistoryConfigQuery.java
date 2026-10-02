package com.kinlin.ai.projection.history.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

import java.util.List;

/**
 * Typed GET /runs/{runId}/history-config response over the agentos_v2.py
 * {@code project_history_config} wire: only the owner-visible configuration the
 * workbench needs to reopen a historical run. Field set follows the verified
 * readers (restoreWorkbenchDraft, legal plugin hydrate); upstream input keys with
 * no frontend reader are dropped and registered. Execution bindings, kernel
 * policy and package data have no path into this DTO.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record HistoryConfigQuery(
        String runId,
        String title,
        String reviewMode,
        List<String> enabledPluginIds,
        HistoryInputQuery input
) implements QueryResponse {
}
