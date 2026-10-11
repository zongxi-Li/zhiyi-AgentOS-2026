package com.kinlin.ai.projection.mission.dto;

import com.kinlin.ai.projection.common.dto.QueryResponse;
import java.util.List;

public record MissionSemanticCommitsQuery(List<MissionSemanticQuery.Commit> items) implements QueryResponse {
    public MissionSemanticCommitsQuery { items = List.copyOf(items); }
}
