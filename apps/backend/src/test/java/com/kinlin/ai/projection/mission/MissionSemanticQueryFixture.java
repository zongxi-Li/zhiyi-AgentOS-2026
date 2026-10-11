package com.kinlin.ai.projection.mission;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Complete wire fixtures matching the Python S00 contracts, including nested audit receipts. */
public final class MissionSemanticQueryFixture {
    public static final String TIME = "2026-10-11T12:00:00.123456+08:00";
    private MissionSemanticQueryFixture() { }

    public static Map<String, Object> constraint() {
        return new LinkedHashMap<>(Map.of("constraintId", "c1", "text", "保留来源",
                "sourceRefs", List.of("ref:constraint")));
    }

    public static Map<String, Object> view() {
        return new LinkedHashMap<>(Map.of("missionId", "mission 001", "semanticStatus", "INITIALIZED",
                "missionRevision", 2, "commitId", "commit-2", "objective", "正式目标",
                "constraints", List.of(constraint()), "sourceReferences", List.of("ref:mission"),
                "sourceStatus", "UNVERIFIED"));
    }

    public static Map<String, Object> state() {
        return new LinkedHashMap<>(Map.of("schemaVersion", 1, "missionId", "mission 001", "missionRevision", 2,
                "objective", "正式目标", "constraints", List.of(constraint()), "sourceRefs", List.of("ref:mission"),
                "lastCommitId", "commit-2", "updatedAt", TIME));
    }

    public static Map<String, Object> commit() {
        return new LinkedHashMap<>(Map.of("commitId", "commit-2", "missionId", "mission 001", "operationId", "edit 1",
                "previousRevision", 1, "missionRevision", 2, "actorId", "owner", "tenantId", "tenant",
                "requestFingerprint", "f".repeat(64), "state", state(), "createdAt", TIME));
    }

    public static Map<String, Object> commits() { return new LinkedHashMap<>(Map.of("items", List.of(commit()))); }

    public static Map<String, Object> result() {
        return new LinkedHashMap<>(Map.of("status", "COMMITTED", "missionId", "mission 001", "operationId", "edit 1",
                "missionRevision", 2, "expectedMissionRevision", 1, "commitId", "commit-2"));
    }

    public static Map<String, Object> receipt() {
        return new LinkedHashMap<>(Map.of("fingerprintVersion", 1, "requestFingerprint", "f".repeat(64),
                "actorId", "owner", "tenantId", "tenant", "result", result(), "createdAt", TIME));
    }

    public static Map<String, Object> decision() {
        return new LinkedHashMap<>(Map.of("operationId", "op 1", "sourceRevision", 1, "targetRevision", 2,
                "decision", "REQUEST_REPLAN", "missionId", "mission 001", "runId", "run 1",
                "actorId", "owner", "tenantId", "tenant", "createdAt", TIME));
    }

    public static Map<String, Object> revision() {
        return new LinkedHashMap<>(Map.of("missionId", "mission 001", "runId", "run 1", "status", "REVISION_CHANGED",
                "sourceRevision", 1, "targetRevision", 2, "decisionStatus", "REPLAN_REQUESTED",
                "runStatus", "cancelled", "impact", "NOT_ANALYZED", "decisions", List.of(decision())));
    }
}
