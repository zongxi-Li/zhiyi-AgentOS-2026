package com.kinlin.ai.projection.trace;

import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.projection.trace.mapper.TraceProjectionMapper;
import org.junit.jupiter.api.Test;

import static com.kinlin.ai.projection.trace.TraceQueryFixture.checkpointCreated;
import static com.kinlin.ai.projection.trace.TraceQueryFixture.dataConsumedLedger;
import static com.kinlin.ai.projection.trace.TraceQueryFixture.envelope;
import static com.kinlin.ai.projection.trace.TraceQueryFixture.event;
import static com.kinlin.ai.projection.trace.TraceQueryFixture.events;
import static com.kinlin.ai.projection.trace.TraceQueryFixture.map;
import static com.kinlin.ai.projection.trace.TraceQueryFixture.modelCalled;
import static com.kinlin.ai.projection.trace.TraceQueryFixture.plannerProgress;
import static com.kinlin.ai.projection.trace.TraceQueryFixture.unknownPayload;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * JSON contract closure for the trace projection: exact envelope/event/payload key
 * sets, NON_NULL absence, the bounded detail-row vocabulary, sentinel reachability
 * and exact counter serialization.
 */
class TraceProjectionSerializationTest {
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private static JsonNode json(Map<String, Object> wire) throws Exception {
        return MAPPER.readTree(MAPPER.writeValueAsString(TraceProjectionMapper.trace(wire)));
    }

    private static Set<String> keys(JsonNode node) {
        Set<String> names = new LinkedHashSet<>();
        node.fieldNames().forEachRemaining(names::add);
        return names;
    }

    @Test
    void envelopeHasExactlySevenTopLevelKeys() throws Exception {
        JsonNode envelope = json(TraceQueryFixture.envelope(
                events(event("run_completed", Map.of())), 1));
        assertEquals(Set.of("runId", "missionId", "workflowId", "domain", "status",
                "eventCount", "events"), keys(envelope));
        JsonNode event = envelope.path("events").get(0);
        assertEquals(Set.of("eventId", "runId", "stepId", "agentName", "eventType",
                "observation", "durationMs", "createdAt", "payload"), keys(event));
    }

    @Test
    void typedPayloadKeysAreExactlyTheReaderDrivenSet() throws Exception {
        JsonNode payload = json(TraceQueryFixture.envelope(
                events(event("model_called", modelCalled())), 1))
                .path("events").get(0).path("payload");
        assertEquals(Set.of("provider", "model", "latencyMs", "finishReason", "details"),
                keys(payload));
        JsonNode detail = payload.path("details").get(0);
        assertEquals(Set.of("key", "value", "kind"), keys(detail));
        Set<String> kinds = new LinkedHashSet<>();
        payload.path("details").forEach(row -> kinds.add(row.path("kind").asText()));
        assertTrue(Set.of("string", "number", "boolean", "list", "object", "redacted", "truncated")
                .containsAll(kinds), "detail kinds must stay in the closed vocabulary: " + kinds);
    }

    @Test
    void unknownEventPayloadSerializesAsEmptyProjection() throws Exception {
        JsonNode payload = json(TraceQueryFixture.envelope(
                events(event("brand_new_event", unknownPayload())), 1))
                .path("events").get(0).path("payload");
        assertEquals(Set.of("details"), keys(payload));
        assertEquals(0, payload.path("details").size());
        assertFalse(MAPPER.writeValueAsString(payload).contains(TraceQueryFixture.SECRET));
    }

    @Test
    void plannerProgressKeepsReaderKeysAndDropsPlantedInternalPolicy() throws Exception {
        JsonNode payload = json(TraceQueryFixture.envelope(
                events(event("task_status_changed", plannerProgress())), 1))
                .path("events").get(0).path("payload");
        assertTrue(payload.path("planningProgress").asBoolean());
        assertEquals(5, payload.path("taskCount").asInt());
        assertEquals("planner", payload.path("category").asText());
        Set<String> keys = keys(payload);
        assertTrue(Set.of("planningProgress", "category", "stage", "status", "kind",
                "attempt", "retryCount", "taskCount", "dependencyCount", "nodeCount",
                "edgeCount", "constraintCount", "requiredCapabilityCount",
                "expectedArtifactCount", "timeoutSeconds", "details").containsAll(keys));
        String body = MAPPER.writeValueAsString(payload);
        assertFalse(body.contains("promptAudit"));
        assertFalse(body.contains("profile"));
        assertFalse(body.contains("selectedBindings"));
        assertFalse(body.contains(TraceQueryFixture.SECRET));
    }

    @Test
    void checkpointCreatedPayloadLosesTheInternalCheckpointReference() throws Exception {
        JsonNode payload = json(TraceQueryFixture.envelope(
                events(event("checkpoint_created", checkpointCreated())), 1))
                .path("events").get(0).path("payload");
        assertEquals(Set.of("details"), keys(payload));
        assertFalse(MAPPER.writeValueAsString(payload).contains("ckpt_1"));
        assertFalse(MAPPER.writeValueAsString(payload).contains(TraceQueryFixture.SECRET));
    }

    @Test
    void producerFieldsAssociationRowsReplaceTheDynamicMap() throws Exception {
        JsonNode payload = json(TraceQueryFixture.envelope(
                events(event("data_consumed", dataConsumedLedger())), 1))
                .path("events").get(0).path("payload");
        JsonNode producerFields = payload.path("producerFields");
        assertEquals(1, producerFields.size());
        assertEquals(Set.of("producerId", "fields"), keys(producerFields.get(0)));
        assertEquals("step_1", producerFields.get(0).path("producerId").asText());
        assertEquals(2, producerFields.get(0).path("fields").size());
        String body = MAPPER.writeValueAsString(payload);
        assertFalse(body.contains("fieldsByProducer"));
    }

    @Test
    void eventCountStaysExactLongThroughSerialization() throws Exception {
        JsonNode envelope = json(TraceQueryFixture.envelope(events(), 3_000_000_000L));
        JsonNode count = envelope.path("eventCount");
        assertTrue(count.isLong(), "a 3e9 event count must serialize as a long");
        assertEquals(3_000_000_000L, count.asLong());
    }

    @Test
    void secretSentinelsNeverReachTheSerializedTrace() throws Exception {
        List<Map<String, Object>> familyEvents = events(
                event("step_scheduled", map("stepIds", List.of("step_1"), "internalState", TraceQueryFixture.SECRET)),
                event("step_succeeded", map("commitId", "commit_1", "outputSummary", "报告",
                        "modelInvocations", List.of(map("provider", "zhipu",
                                "promptVersion", "[redacted]",
                                "internalExtension", map("nested", TraceQueryFixture.SECRET))))),
                event("model_called", modelCalled()),
                event("tool_called", map("tool", "web_search", "name", "web_search",
                        "status", "succeeded", "latencyMs", 210)),
                event("data_consumed", dataConsumedLedger()),
                event("run_recovered", map("failedResources", List.of(
                                map("stepId", "step_1", "resourceId", "res_1", "error", "refused")),
                        "retryStepIds", List.of("step_1"))),
                event("task_status_changed", plannerProgress()),
                event("brand_new_event", unknownPayload()),
                event("checkpoint_created", checkpointCreated()));
        String body = MAPPER.writeValueAsString(
                TraceProjectionMapper.trace(TraceQueryFixture.envelope(familyEvents, 9)));
        assertFalse(body.contains(TraceQueryFixture.SECRET), "planted secrets must not reach the wire");
        assertFalse(body.contains("commitId"), "commitId must be deleted from step_succeeded");
        assertFalse(body.contains("checkpointId"));
        assertFalse(body.contains("promptAudit"));
        assertFalse(body.contains("pendingMemory"));
        assertFalse(body.contains("patchId"));
        assertFalse(body.contains("graphId"));
        assertFalse(body.contains("traceRef"));
    }
}
