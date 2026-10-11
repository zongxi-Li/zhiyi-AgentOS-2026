package com.kinlin.ai.projection.mission.mapper;

import com.kinlin.ai.projection.mission.dto.MissionRunRevisionQuery;
import com.kinlin.ai.projection.mission.dto.MissionSemanticCommitsQuery;
import com.kinlin.ai.projection.mission.dto.MissionSemanticQuery;
import com.kinlin.ai.projection.mission.dto.MissionSemanticReceiptQuery;
import java.time.DateTimeException;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.function.Function;

import static com.kinlin.ai.projection.common.mapper.QueryWire.integer;
import static com.kinlin.ai.projection.common.mapper.QueryWire.invalid;
import static com.kinlin.ai.projection.common.mapper.QueryWire.object;
import static com.kinlin.ai.projection.common.mapper.QueryWire.requiredText;
import static com.kinlin.ai.projection.common.mapper.QueryWire.text;

/** Pure recursive whitelist of the S00 read contracts; writes and state authority remain upstream. */
public final class MissionSemanticProjectionMapper {
    private MissionSemanticProjectionMapper() { }

    public static MissionSemanticQuery view(Map<String, Object> wire) {
        return new MissionSemanticQuery(requiredText(wire, "missionId"), requiredText(wire, "semanticStatus"),
                revision(wire, "missionRevision", 0), text(wire, "commitId"), text(wire, "objective"),
                entries(wire, "constraints", MissionSemanticProjectionMapper::constraint),
                references(wire, "sourceReferences"), requiredText(wire, "sourceStatus"));
    }

    public static MissionSemanticCommitsQuery commits(Map<String, Object> wire) {
        return new MissionSemanticCommitsQuery(entries(wire, "items", MissionSemanticProjectionMapper::commit));
    }

    public static MissionSemanticReceiptQuery receipt(Map<String, Object> wire) {
        return new MissionSemanticReceiptQuery(Math.toIntExact(revision(wire, "fingerprintVersion", 1)),
                requiredText(wire, "requestFingerprint"), requiredText(wire, "actorId"), requiredText(wire, "tenantId"),
                result(object(wire.get("result"))), time(wire, "createdAt"));
    }

    public static MissionRunRevisionQuery revision(Map<String, Object> wire) {
        return new MissionRunRevisionQuery(requiredText(wire, "missionId"), requiredText(wire, "runId"),
                requiredText(wire, "status"), revision(wire, "sourceRevision", 0), revision(wire, "targetRevision", 0),
                requiredText(wire, "decisionStatus"), requiredText(wire, "runStatus"), requiredText(wire, "impact"),
                entries(wire, "decisions", MissionSemanticProjectionMapper::decision), text(wire, "successorRunId"));
    }

    private static MissionSemanticQuery.Constraint constraint(Map<?, ?> wire) {
        return new MissionSemanticQuery.Constraint(requiredText(wire, "constraintId"), requiredText(wire, "text"),
                references(wire, "sourceRefs"));
    }

    private static MissionSemanticQuery.State state(Map<?, ?> wire) {
        return new MissionSemanticQuery.State(Math.toIntExact(revision(wire, "schemaVersion", 1)),
                requiredText(wire, "missionId"), revision(wire, "missionRevision", 1), requiredText(wire, "objective"),
                entries(wire, "constraints", MissionSemanticProjectionMapper::constraint), references(wire, "sourceRefs"),
                requiredText(wire, "lastCommitId"), time(wire, "updatedAt"));
    }

    private static MissionSemanticQuery.Commit commit(Map<?, ?> wire) {
        return new MissionSemanticQuery.Commit(requiredText(wire, "commitId"), requiredText(wire, "missionId"),
                requiredText(wire, "operationId"), revision(wire, "previousRevision", 0), revision(wire, "missionRevision", 1),
                requiredText(wire, "actorId"), requiredText(wire, "tenantId"), requiredText(wire, "requestFingerprint"),
                state(object(wire.get("state"))), time(wire, "createdAt"));
    }

    private static MissionSemanticQuery.Result result(Map<?, ?> wire) {
        return new MissionSemanticQuery.Result(requiredText(wire, "status"), requiredText(wire, "missionId"),
                requiredText(wire, "operationId"), revision(wire, "missionRevision", 0),
                revision(wire, "expectedMissionRevision", 0), text(wire, "commitId"));
    }

    private static MissionRunRevisionQuery.Decision decision(Map<?, ?> wire) {
        return new MissionRunRevisionQuery.Decision(requiredText(wire, "operationId"), revision(wire, "sourceRevision", 0),
                revision(wire, "targetRevision", 1), requiredText(wire, "decision"), requiredText(wire, "missionId"),
                requiredText(wire, "runId"), requiredText(wire, "actorId"), requiredText(wire, "tenantId"), time(wire, "createdAt"));
    }

    private static long revision(Map<?, ?> wire, String field, long minimum) {
        Long value = integer(wire, field);
        if (value == null || value < minimum) { throw invalid(); }
        return value;
    }

    private static String time(Map<?, ?> wire, String field) {
        String value = requiredText(wire, field);
        try { OffsetDateTime.parse(value); }
        catch (DateTimeException malformed) { throw invalid(); }
        return value;
    }

    private static List<?> array(Map<?, ?> wire, String field) {
        if (wire.get(field) instanceof List<?> values) { return values; }
        throw invalid();
    }

    private static List<String> references(Map<?, ?> wire, String field) {
        return array(wire, field).stream().map(value -> {
            if (value instanceof String reference && !reference.isBlank()) { return reference; }
            throw invalid();
        }).toList();
    }

    private static <T> List<T> entries(Map<?, ?> wire, String field, Function<Map<?, ?>, T> mapper) {
        return array(wire, field).stream().map(value -> mapper.apply(object(value))).toList();
    }
}
