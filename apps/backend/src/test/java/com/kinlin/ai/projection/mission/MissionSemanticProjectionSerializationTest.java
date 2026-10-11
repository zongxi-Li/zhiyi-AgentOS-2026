package com.kinlin.ai.projection.mission;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.kinlin.ai.projection.mission.mapper.MissionSemanticProjectionMapper;
import org.junit.jupiter.api.Test;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

class MissionSemanticProjectionSerializationTest {
    private final ObjectMapper jackson = new ObjectMapper();
    private static final String SECRET = "INTERNAL-EXECUTION-STATE";

    private JsonNode json(Object value) throws Exception {
        // Compare the actual wire JSON, not Jackson's Integer/Long in-memory node classes.
        return jackson.readTree(jackson.writeValueAsString(value));
    }

    @Test
    void currentSemanticsPreserveAllPublicFieldsAndDoNotRetainWireObjects() throws Exception {
        var wire = MissionSemanticQueryFixture.view();
        var expected = json(wire);
        wire.put("executionState", SECRET);
        var result = MissionSemanticProjectionMapper.view(wire);
        assertEquals(expected, json(result));
        wire.clear();
        assertEquals(expected, json(result));
        assertThrows(UnsupportedOperationException.class, () -> result.constraints().clear());
        assertThrows(UnsupportedOperationException.class, () -> result.constraints().get(0).sourceRefs().clear());
    }

    @Test
    void uninitializedMissionKeepsExplicitNullsZeroRevisionAndEmptyCollections() throws Exception {
        var wire = MissionSemanticQueryFixture.view();
        wire.put("semanticStatus", "UNINITIALIZED"); wire.put("missionRevision", 0);
        wire.put("commitId", null); wire.put("objective", null); wire.put("constraints", List.of());
        wire.put("sourceReferences", List.of()); wire.put("sourceStatus", "NOT_APPLICABLE");
        var result = MissionSemanticProjectionMapper.view(wire);
        assertEquals(json(wire), json(result));
        assertNull(result.objective());
        assertNull(result.commitId());
    }

    @Test
    void historyRecursivelyProjectsCommittedStateWithoutDroppingAuditIdentity() throws Exception {
        var state = MissionSemanticQueryFixture.state();
        var constraint = MissionSemanticQueryFixture.constraint();
        state.put("constraints", List.of(constraint));
        var commit = MissionSemanticQueryFixture.commit(); commit.put("state", state);
        var wire = Map.<String, Object>of("items", List.of(commit));
        var expected = json(wire);
        state.put("taskPlan", SECRET); constraint.put("binding", SECRET); commit.put("runtime", SECRET);
        var result = MissionSemanticProjectionMapper.commits(wire);
        assertEquals(expected, json(result));
        assertEquals("owner", result.items().get(0).actorId());
        assertEquals(MissionSemanticQueryFixture.TIME, result.items().get(0).state().updatedAt());
        assertFalse(jackson.writeValueAsString(result).contains(SECRET));
        commit.clear(); state.clear(); constraint.clear();
        assertEquals(expected, json(result));
        assertThrows(UnsupportedOperationException.class, () -> result.items().clear());
        assertTrue(MissionSemanticProjectionMapper.commits(Map.of("items", List.of())).items().isEmpty());
    }

    @Test
    void receiptPreservesCommittedNoOpAndConflictResultsIncludingNullableCommit() throws Exception {
        for (String status : List.of("COMMITTED", "NO_OP", "REVISION_CONFLICT", "OPERATION_CONFLICT")) {
            var body = MissionSemanticQueryFixture.result(); body.put("status", status);
            if (!status.equals("COMMITTED")) { body.put("commitId", null); }
            var wire = MissionSemanticQueryFixture.receipt(); wire.put("result", body);
            var expected = json(wire);
            wire.put("checkpoint", SECRET); body.put("executionState", SECRET);
            assertEquals(expected, json(MissionSemanticProjectionMapper.receipt(wire)));
        }
    }

    @Test
    void revisionKeepsHistoricalDecisionsAndOmitsAbsentSuccessor() throws Exception {
        var decision = MissionSemanticQueryFixture.decision();
        var wire = MissionSemanticQueryFixture.revision(); wire.put("decisions", List.of(decision));
        // A later Mission revision does not rewrite the receipt's previously chosen revision.
        wire.put("targetRevision", 3); wire.put("decisionStatus", "DECISION_STALE");
        var expected = json(wire);
        decision.put("graphPatchRefs", SECRET);
        var result = MissionSemanticProjectionMapper.revision(wire);
        assertEquals(expected, json(result));
        assertEquals(2, result.decisions().get(0).targetRevision());
        assertFalse(json(result).has("successorRunId"));
        wire.put("successorRunId", "successor-1"); wire.put("decisionStatus", "SUCCESSOR_CREATED");
        assertEquals("successor-1", MissionSemanticProjectionMapper.revision(wire).successorRunId());
        assertThrows(UnsupportedOperationException.class, () -> result.decisions().clear());
    }

    @Test
    void currentAndLegacyRevisionObservationsKeepZeroAndEmptyHistory() throws Exception {
        for (String status : List.of("CURRENT", "LEGACY_UNBOUND")) {
            var wire = MissionSemanticQueryFixture.revision(); wire.put("status", status);
            wire.put("sourceRevision", status.equals("CURRENT") ? 2 : 0);
            wire.put("targetRevision", status.equals("CURRENT") ? 2 : 0);
            wire.put("decisions", List.of()); wire.put("decisionStatus", "UNDECIDED");
            assertEquals(json(wire), json(MissionSemanticProjectionMapper.revision(wire)));
        }
    }

    @Test
    void requiredContractsRejectMissingListsMalformedNumbersAndTimestamps() {
        assertThrows(IllegalArgumentException.class, () -> MissionSemanticProjectionMapper.commits(Map.of()));
        assertThrows(IllegalArgumentException.class, () -> MissionSemanticProjectionMapper.commits(Map.of("items", List.of("bad"))));
        for (Object invalid : List.of("2", true, -1, 1.5)) {
            var wire = MissionSemanticQueryFixture.view(); wire.put("missionRevision", invalid);
            assertThrows(RuntimeException.class, () -> MissionSemanticProjectionMapper.view(wire));
        }
        var view = MissionSemanticQueryFixture.view(); view.put("constraints", null);
        assertThrows(IllegalArgumentException.class, () -> MissionSemanticProjectionMapper.view(view));
        var receipt = MissionSemanticQueryFixture.receipt(); receipt.put("createdAt", SECRET);
        var invalidTime = assertThrows(IllegalArgumentException.class, () -> MissionSemanticProjectionMapper.receipt(receipt));
        assertFalse(invalidTime.getMessage().contains(SECRET));
        var observation = MissionSemanticQueryFixture.revision(); observation.put("decisions", null);
        assertThrows(IllegalArgumentException.class, () -> MissionSemanticProjectionMapper.revision(observation));
        var malformedDecision = MissionSemanticQueryFixture.decision(); malformedDecision.put("sourceRevision", "1");
        observation.put("decisions", List.of(malformedDecision));
        assertThrows(IllegalArgumentException.class, () -> MissionSemanticProjectionMapper.revision(observation));
        var state = MissionSemanticQueryFixture.state(); state.put("updatedAt", SECRET);
        var commit = MissionSemanticQueryFixture.commit(); commit.put("state", state);
        assertThrows(IllegalArgumentException.class, () -> MissionSemanticProjectionMapper.commits(Map.of("items", List.of(commit))));
    }

    @Test
    void revisionsAreNotTruncatedToJavaInt() {
        var wire = MissionSemanticQueryFixture.view(); wire.put("missionRevision", 3_000_000_000L);
        assertEquals(3_000_000_000L, MissionSemanticProjectionMapper.view(wire).missionRevision());
    }
}
