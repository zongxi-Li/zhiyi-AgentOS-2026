package com.kinlin.ai.projection.mission.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;
import java.util.List;

/** Version observation and historical user decisions; no execution state or semantic impact claim. */
public record MissionRunRevisionQuery(String missionId, String runId, String status, long sourceRevision,
                                      long targetRevision, String decisionStatus, String runStatus, String impact,
                                      List<Decision> decisions,
                                      @JsonInclude(JsonInclude.Include.NON_NULL) String successorRunId) implements QueryResponse {
    public MissionRunRevisionQuery { decisions = List.copyOf(decisions); }

    public record Decision(String operationId, long sourceRevision, long targetRevision, String decision,
                           String missionId, String runId, String actorId, String tenantId, String createdAt) { }
}
