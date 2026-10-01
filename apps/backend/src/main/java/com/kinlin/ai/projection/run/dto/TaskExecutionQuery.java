package com.kinlin.ai.projection.run.dto;

import java.util.List;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/** Explicit observation fields; never an executable runtime snapshot. */
public record TaskExecutionQuery(
        com.kinlin.ai.projection.mission.dto.MissionDetailQuery.TaskSummary task,
        String acgNodeId,
        List<AttemptDetailQuery> attempts
) implements QueryResponse {
    public TaskExecutionQuery {
        attempts = List.copyOf(attempts);
    }
 }
