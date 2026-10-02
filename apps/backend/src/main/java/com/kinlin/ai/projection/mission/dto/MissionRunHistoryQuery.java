package com.kinlin.ai.projection.mission.dto;

import com.kinlin.ai.projection.common.dto.QueryResponse;
import java.util.List;

public record MissionRunHistoryQuery(String missionId, List<MissionRunSummaryQuery> runs) implements QueryResponse {
    public MissionRunHistoryQuery { runs = List.copyOf(runs); }
}
