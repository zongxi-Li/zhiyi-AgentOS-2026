package com.kinlin.ai.projection.run;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.projection.run.mapper.RunProjectionMapper;
import org.junit.jupiter.api.Test;
import java.util.List;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.*;

class RunProjectionBoundaryTest {
    private final ObjectMapper jackson = new ObjectMapper();
    @Test
    void publicReviewOutputsAndLineageSurviveWhileRuntimeStateCannotSerialize() throws Exception {
        Map<String, Object> wire = Map.of("runId", "run_1", "status", "waiting_review", "steps", List.of(),
                "executionState", Map.of("reviewPayload", Map.of("subjectType", "control", "subjectId", "join_1", "reasonCode", "CONSENSUS_UNRESOLVED", "auditDecisionRef", "secret"),
                        "outputRefs", Map.of("step_1", "out_1"), "outputSummaries", Map.of("step_1", "public answer"),
                        "parentRunId", "parent_1", "checkpointId", "secret", "resourceBindings", Map.of("secret", "secret"),
                        "controlFrames", List.of(Map.of("secret", "secret")), "scheduler", Map.of("secret", "secret")));
        var result = RunProjectionMapper.run(wire);
        assertEquals("join_1", result.review().subjectId());
        assertEquals("out_1", result.outputs().get(0).outputRef());
        assertEquals("parent_1", result.lineage().parentRunId());
        String encoded = jackson.writeValueAsString(result);
        assertFalse(encoded.contains("secret"));
        for (String key : List.of("executionState", "checkpoint", "resourceBindings", "scheduler", "controlFrames")) {
            assertFalse(encoded.contains(key), key);
        }
        assertThrows(UnsupportedOperationException.class, () -> result.outputs().clear());
    }
    @Test
    void treeKeepsLifecycleFactsAndResourceUsageWithoutBindingOrPackage() throws Exception {
        var attempt = Map.of("attempt", Map.of("attemptId", "a"),
                "executionBinding", Map.of("bindingId", "secret", "resourceId", "resource_1", "agentId", "agent_1", "metadata", Map.of("secret", "secret")),
                "executions", List.of(Map.of("stepExecutionId", "e", "input", Map.of("secret", "secret"))));
        var node = Map.of("task", Map.of("taskId", "t"), "attempts", List.of(attempt));
        var result = RunProjectionMapper.tree(Map.of(
                "run", Map.of("runId", "r", "missionId", "m", "graphVersion", 1, "checkpoint", Map.of("secret", "secret")),
                "blueprint", Map.of("graphId", "graph_1", "version", 3, "missionId", "m", "graph", Map.of("nodes", List.of(), "edges", List.of(), "metadata", Map.of("secret", "secret"))),
                "nodes", List.of(node),
                "operational", Map.of("package", Map.of("secret", "secret"), "nodeExecutions", List.of(Map.of("stepId", "t", "attemptId", "a", "phase", "committed", "operationId", "secret")))));
        assertEquals("resource_1", result.nodes().get(0).attempts().get(0).resourceUse().resourceId());
        assertEquals("committed", result.lifecycles().get(0).phase());
        assertEquals("graph_1", result.graph().graphId());
        assertEquals(3, result.graph().graphVersion());
        String encoded = jackson.writeValueAsString(result);
        assertFalse(encoded.contains("secret"));
        assertFalse(encoded.contains("operational")); assertFalse(encoded.contains("executionBinding"));
    }
    @Test
    void lifecycleSequencePreservesLatestLoopObservationWithoutExposingInternalOrderKeys() throws Exception {
        var records = List.of(
                Map.of("stepId", "s", "attemptId", "a", "phase", "committed", "loopPath", List.of(2), "executionInstanceId", "latest"),
                Map.of("stepId", "s", "attemptId", "a", "phase", "failed", "loopPath", List.of(1), "executionInstanceId", "previous"));
        var result = RunProjectionMapper.tree(Map.of("run", Map.of("runId", "r", "graphVersion", 1),
                "blueprint", Map.of("graph", Map.of("nodes", List.of(), "edges", List.of())),
                "nodes", List.of(), "operational", Map.of("nodeExecutions", records)));
        assertEquals(List.of("failed", "committed"), result.lifecycles().stream().map(item -> item.phase()).toList());
        assertEquals(List.of(0, 1), result.lifecycles().stream().map(item -> item.sequence()).toList());
        assertFalse(jackson.writeValueAsString(result).contains("loopPath"));
        assertEquals("committed", records.get(0).get("phase"), "mapping must leave the source order untouched");
    }
    @Test
    void malformedRequiredIdentityCannotBeFabricated() {
        assertThrows(IllegalArgumentException.class, () -> RunProjectionMapper.run(Map.of("status", "completed")));
        assertThrows(IllegalArgumentException.class, () -> RunProjectionMapper.run(Map.of("runId", "r", "steps", "invalid")));
    }
}
