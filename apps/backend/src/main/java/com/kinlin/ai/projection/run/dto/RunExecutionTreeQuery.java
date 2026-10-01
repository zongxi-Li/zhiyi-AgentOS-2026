package com.kinlin.ai.projection.run.dto;

import java.util.List;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/** Explicit observation fields; never an executable runtime snapshot. */
public record RunExecutionTreeQuery(
        com.kinlin.ai.projection.mission.dto.MissionRunSummaryQuery run,
        com.kinlin.ai.projection.graph.dto.GraphQuery graph,
        List<TaskExecutionQuery> nodes,
        RunLineageQuery lineage,
        List<NodeLifecycleQuery> lifecycles
) implements QueryResponse {
    public RunExecutionTreeQuery {
        nodes = List.copyOf(nodes);
        lifecycles = List.copyOf(lifecycles);
    }
 }
