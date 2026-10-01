package com.kinlin.ai.projection.mission.dto;

import com.kinlin.ai.projection.common.dto.QueryResponse;
import java.util.List;

/** Observation-only summaries. No executable topology or stored domain model is retained. */
public record MissionDetailQuery(MissionSummary mission, List<TaskSummary> tasks,
                                 List<GraphSummary> graphs, List<MissionRunSummaryQuery> runs) implements QueryResponse {
    public MissionDetailQuery {
        tasks = List.copyOf(tasks);
        graphs = List.copyOf(graphs);
        runs = List.copyOf(runs);
    }

    public record MissionSummary(String missionId, String goal, String description, String status,
                                 String createdAt, String updatedAt) { }

    public record TaskSummary(String taskId, String missionId, String semanticTaskKey, String parentTaskId,
                              String title, String objective, String status, int constraintCount) { }

    public record GraphSummary(String graphId, int version, String createdAt) { }
}
