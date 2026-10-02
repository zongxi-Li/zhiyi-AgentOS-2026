package com.kinlin.ai.projection.workspace.dto;

import java.util.List;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;
import com.kinlin.ai.projection.graph.dto.GraphEdgeQuery;
import com.kinlin.ai.projection.graph.dto.GraphNodeQuery;

/**
 * Blueprint display graph behind the workspace {@code activeGraph} snapshot
 * (workspace.py#_graph_snapshot). Deliberately NOT the {@code /runs/{id}/graph} wire:
 * no runId, no step-state lists, no binding/patch references — this is the stored
 * blueprint topology with the envelope's public identifiers and versions.
 *
 * <p>Dropped from the raw snapshot: {@code blueprintId} (no frontend consumer; the
 * entry-level blueprintId stays on WorkspaceEntryQuery), blueprint bookkeeping
 * (createdAt/updatedAt/priority/metadata) and every node/edge execution spec
 * (inputSpec/outputSpec/schema/loopSpec/consensusSpec/parallelSpec/conditionSpec/
 * memoryIds/skillIds/evidenceIds/retryLimit/timeout/maxConcurrency/modelName/priority) —
 * node/edge rows are re-mapped through the existing GraphProjectionMapper display rules.
 * {@code taskPlanVersion} is the public plan version; absent when the run has no
 * resolvable plan snapshot.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record WorkspaceGraphQuery(
        String graphId,
        Integer graphVersion,
        String missionId,
        Integer taskPlanVersion,
        String objective,
        String complexityLevel,
        List<GraphNodeQuery> nodes,
        List<GraphEdgeQuery> edges
) implements QueryResponse {
    public WorkspaceGraphQuery {
        nodes = List.copyOf(nodes);
        edges = List.copyOf(edges);
    }
}
