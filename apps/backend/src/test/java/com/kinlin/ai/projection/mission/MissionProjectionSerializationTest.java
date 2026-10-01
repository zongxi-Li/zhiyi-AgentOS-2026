package com.kinlin.ai.projection.mission;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.projection.mission.dto.MissionDetailQuery;
import com.kinlin.ai.projection.mission.mapper.MissionProjectionMapper;
import org.junit.jupiter.api.Test;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import static org.junit.jupiter.api.Assertions.*;

class MissionProjectionSerializationTest {
    private final ObjectMapper jackson = new ObjectMapper();

    @Test
    void detailIsARecursiveWhitelistAndDoesNotRetainDomainObjects() throws Exception {
        Map<String, Object> wire = MissionQueryFixture.detail();
        MissionDetailQuery result = MissionProjectionMapper.detail(wire);
        String encoded = jackson.writeValueAsString(result);
        JsonNode json = jackson.readTree(encoded);
        assertFields(json, "mission", "tasks", "graphs", "runs");
        assertFields(json.get("mission"), "missionId", "goal", "description", "status", "createdAt", "updatedAt");
        assertFields(json.get("tasks").get(0), "taskId", "missionId", "semanticTaskKey", "parentTaskId",
                "title", "objective", "status", "constraintCount");
        assertFields(json.get("graphs").get(0), "graphId", "version", "createdAt");
        assertFields(json.get("runs").get(0), "runId", "missionId", "status", "graphVersion", "startedAt", "finishedAt", "createdAt", "updatedAt");
        assertEquals("审核合同", result.mission().goal());
        assertEquals(MissionQueryFixture.TIME, result.mission().createdAt());
        assertEquals(1, result.tasks().get(0).constraintCount());
        assertNull(result.tasks().get(0).semanticTaskKey());
        assertNull(result.runs().get(0).finishedAt());
        assertFalse(encoded.contains(MissionQueryFixture.SECRET));
        assertNotNull(wire.get("TaskPlan"));
        wire.clear();
        assertEquals(encoded, jackson.writeValueAsString(result));
        assertThrows(UnsupportedOperationException.class, () -> result.runs().clear());
    }

    @Test
    void historyKeepsOrderUnknownStatusAndAllLifecycleTimesWithoutState() throws Exception {
        Map<String, Object> first = MissionQueryFixture.run();
        first.put("status", "future_observed_status");
        Map<String, Object> second = MissionQueryFixture.run();
        second.put("runId", "run_2");
        second.put("status", "pending");
        second.put("startedAt", null);
        var result = MissionProjectionMapper.history(Map.of("missionId", "mission_1", "runs", List.of(first, second)));
        assertEquals(List.of("run_1", "run_2"), result.runs().stream().map(run -> run.runId()).toList());
        assertEquals("future_observed_status", result.runs().get(0).status());
        assertNull(result.runs().get(1).startedAt());
        String encoded = jackson.writeValueAsString(result);
        assertFalse(encoded.contains(MissionQueryFixture.SECRET));
        assertFalse(encoded.contains("checkpoint"));
        assertFalse(encoded.contains("executionState"));
        assertFields(jackson.readTree(encoded), "missionId", "runs");
    }

    @Test
    void emptyCollectionsRemainEmptyAndRequiredFieldsNeverBecomeFabricatedSuccess() {
        Map<String, Object> wire = MissionQueryFixture.detail();
        wire.put("tasks", List.of()); wire.put("blueprints", List.of()); wire.put("runs", List.of());
        var result = MissionProjectionMapper.detail(wire);
        assertTrue(result.tasks().isEmpty()); assertTrue(result.graphs().isEmpty()); assertTrue(result.runs().isEmpty());
        for (String field : List.of("mission", "tasks", "blueprints", "runs")) {
            var incomplete = MissionQueryFixture.detail(); incomplete.remove(field);
            assertThrows(IllegalArgumentException.class, () -> MissionProjectionMapper.detail(incomplete), field);
        }
        assertThrows(IllegalArgumentException.class, () -> MissionProjectionMapper.history(Map.of("runs", List.of())));
        assertThrows(IllegalArgumentException.class, () -> MissionProjectionMapper.history(Map.of("missionId", "m", "runs", "invalid")));
    }

    @Test
    void malformedScalarTimeAndVersionAreRejectedWithoutEchoingPrivateValues() {
        for (Object invalid : List.of("3", 1.5, 0)) {
            var run = MissionQueryFixture.run(); run.put("graphVersion", invalid);
            assertThrows(RuntimeException.class, () -> MissionProjectionMapper.history(Map.of("missionId", "m", "runs", List.of(run))));
        }
        var invalidTimeRun = MissionQueryFixture.run(); invalidTimeRun.put("createdAt", MissionQueryFixture.SECRET);
        var error = assertThrows(IllegalArgumentException.class,
                () -> MissionProjectionMapper.history(Map.of("missionId", "m", "runs", List.of(invalidTimeRun))));
        assertFalse(error.getMessage().contains(MissionQueryFixture.SECRET));
        var invalidRun = MissionQueryFixture.run(); invalidRun.put("runId", Map.of("secret", MissionQueryFixture.SECRET));
        assertThrows(IllegalArgumentException.class,
                () -> MissionProjectionMapper.history(Map.of("missionId", "m", "runs", List.of(invalidRun))));
    }

    @Test
    void listIsAWhitelistEnvelopeWithoutOwnerIdentityOrInternalFields() throws Exception {
        Map<String, Object> wire = MissionQueryFixture.list();
        Map<String, Object> idle = MissionQueryFixture.listItem();
        idle.put("missionId", "mission_2");
        idle.put("latestRunId", null);
        idle.put("latestRunStatus", null);
        idle.put("runCount", 0);
        wire.put("items", List.of(MissionQueryFixture.listItem(), idle));
        var result = MissionProjectionMapper.list(wire);
        String encoded = jackson.writeValueAsString(result);
        assertFields(jackson.readTree(encoded), "items", "total", "page", "pageSize", "source");
        assertFields(jackson.readTree(encoded).get("items").get(0), "missionId", "title", "description",
                "status", "latestRunId", "latestRunStatus", "createdAt", "updatedAt", "runCount");
        assertEquals(List.of("mission_1", "mission_2"), result.items().stream().map(item -> item.missionId()).toList());
        assertEquals("agentos-v2", result.source());
        assertEquals(MissionQueryFixture.TIME, result.items().get(0).createdAt());
        assertNull(result.items().get(1).latestRunId());
        assertEquals(0, result.items().get(1).runCount());
        assertFalse(encoded.contains(MissionQueryFixture.SECRET));
        wire.clear();
        assertEquals(encoded, jackson.writeValueAsString(result));
        assertThrows(UnsupportedOperationException.class, () -> result.items().clear());
    }

    @Test
    void listKeepsEmptyPagesAndRejectsMissingOrInvalidContractFields() {
        var empty = MissionProjectionMapper.list(Map.of("items", List.of(), "total", 0, "page", 1, "pageSize", 20));
        assertTrue(empty.items().isEmpty());
        for (String field : List.of("items", "total", "page", "pageSize")) {
            var incomplete = MissionQueryFixture.list(); incomplete.remove(field);
            assertThrows(IllegalArgumentException.class, () -> MissionProjectionMapper.list(incomplete), field);
        }
        var noItemId = MissionQueryFixture.list();
        noItemId.put("items", List.of(Map.of("title", "缺少标识")));
        assertThrows(IllegalArgumentException.class, () -> MissionProjectionMapper.list(noItemId));
        var negativeCount = MissionQueryFixture.list();
        ((Map<String, Object>) ((List<?>) negativeCount.get("items")).get(0)).put("runCount", -1);
        assertThrows(RuntimeException.class, () -> MissionProjectionMapper.list(negativeCount));
        var invalidTime = MissionQueryFixture.list();
        ((Map<String, Object>) ((List<?>) invalidTime.get("items")).get(0)).put("updatedAt", MissionQueryFixture.SECRET);
        assertThrows(RuntimeException.class, () -> MissionProjectionMapper.list(invalidTime));
    }

    private void assertFields(JsonNode node, String... expected) {
        Set<String> actual = new HashSet<>(); node.fieldNames().forEachRemaining(actual::add);
        assertEquals(Set.of(expected), actual);
    }
}
