package com.kinlin.ai.projection.history.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

import java.util.List;

/**
 * The whitelisted reopen configuration fields with verified frontend readers.
 * {@code pluginData} keeps the per-plugin flat scalar configuration as typed
 * association rows (pluginId → named scalar entries): the plugin set is closed
 * (kinlin.legal, industrial) and both emit flat scalars only, so no nested or
 * free-form structure is approved here.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record HistoryInputQuery(
        String taskGoal,
        String userIntent,
        String materialText,
        String contractText,
        List<String> materialIds,
        List<String> constraints,
        List<String> expectedArtifacts,
        String planningMode,
        String planningDiversity,
        String capabilityProfile,
        String thinkingMode,
        String reasoningEffort,
        Long planningSeed,
        Boolean webSearchEnabled,
        List<HistoryPluginDataQuery> pluginData
) implements QueryResponse {
}
