package com.kinlin.ai.projection.mission.dto;

import com.kinlin.ai.projection.common.dto.QueryResponse;
import java.util.List;

/** Current formal semantics, never inferred from the legacy Mission title or input. */
public record MissionSemanticQuery(String missionId, String semanticStatus, long missionRevision,
                                   String commitId, String objective, List<Constraint> constraints,
                                   List<String> sourceReferences, String sourceStatus) implements QueryResponse {
    public MissionSemanticQuery {
        constraints = List.copyOf(constraints);
        sourceReferences = List.copyOf(sourceReferences);
    }

    public record Constraint(String constraintId, String text, List<String> sourceRefs) {
        public Constraint { sourceRefs = List.copyOf(sourceRefs); }
    }

    public record State(int schemaVersion, String missionId, long missionRevision, String objective,
                        List<Constraint> constraints, List<String> sourceRefs, String lastCommitId, String updatedAt) {
        public State {
            constraints = List.copyOf(constraints);
            sourceRefs = List.copyOf(sourceRefs);
        }
    }

    public record Commit(String commitId, String missionId, String operationId, long previousRevision,
                         long missionRevision, String actorId, String tenantId, String requestFingerprint,
                         State state, String createdAt) { }

    public record Result(String status, String missionId, String operationId, long missionRevision,
                         long expectedMissionRevision, String commitId) { }
}
