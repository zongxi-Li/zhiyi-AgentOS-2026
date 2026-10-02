package com.kinlin.ai.projection.trace;

import java.util.List;
import java.util.Map;

import com.kinlin.ai.projection.trace.dto.TraceEventQuery;
import com.kinlin.ai.projection.trace.dto.TracePayloadQuery;
import com.kinlin.ai.projection.trace.dto.TraceProducerFieldsQuery;
import com.kinlin.ai.projection.trace.dto.TracePublicDetailQuery;
import com.kinlin.ai.projection.trace.dto.TraceQuery;
import com.kinlin.ai.projection.trace.mapper.TraceProjectionMapper;
import org.junit.jupiter.api.Test;

import static com.kinlin.ai.projection.trace.TraceQueryFixture.dataConsumedLedger;
import static com.kinlin.ai.projection.trace.TraceQueryFixture.envelope;
import static com.kinlin.ai.projection.trace.TraceQueryFixture.event;
import static com.kinlin.ai.projection.trace.TraceQueryFixture.events;
import static com.kinlin.ai.projection.trace.TraceQueryFixture.map;
import static com.kinlin.ai.projection.trace.TraceQueryFixture.modelCalled;
import static com.kinlin.ai.projection.trace.TraceQueryFixture.modelCalledMistypedLatency;
import static com.kinlin.ai.projection.trace.TraceQueryFixture.plannerDecision;
import static com.kinlin.ai.projection.trace.TraceQueryFixture.runRecoveredFailover;
import static com.kinlin.ai.projection.trace.TraceQueryFixture.unknownPayload;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Mapper contract over the trace wire: envelope and skeleton structure, per-family
 * whitelist projection, sentinel and mistyped-key behavior, unknown events, upstream
 * order/eventCount semantics and the numeric exactness rules.
 */
class TraceProjectionMapperTest {

    private static TracePayloadQuery payloadOf(Map<String, Object> wireEvent) {
        TraceQuery trace = TraceProjectionMapper.trace(envelope(events(wireEvent), 1));
        assertEquals(1, trace.events().size());
        return trace.events().get(0).payload();
    }

    @Test
    void envelopeKeepsUpstreamSemanticsWithoutReorderingOrRecounting() {
        Map<String, Object> late = event("run_completed", Map.of());
        Map<String, Object> early = map("eventId", "evt_early", "runId", "run_1", "stepId", null,
                "agentName", null, "eventType", "step_scheduled", "observation", "",
                "payload", map("stepIds", List.of("step_1")), "durationMs", 0,
                "createdAt", "2026-10-02T09:00:00Z");
        TraceQuery trace = TraceProjectionMapper.trace(envelope(events(late, early), 5));
        assertEquals(5, trace.eventCount());
        assertEquals(2, trace.events().size());
        // Upstream order is preserved even when createdAt is out of order; the
        // workspace view legitimately yields eventCount > events.size().
        assertEquals("evt_early", trace.events().get(1).eventId());
        assertEquals("run_1", trace.runId());
        assertEquals("mission_1", trace.missionId());
        assertEquals("completed", trace.status());
    }

    @Test
    void modelCalledKeepsReaderKeysAndRedactedMarkersWithoutInventingNumbers() {
        TracePayloadQuery payload = payloadOf(event("model_called", modelCalled()));
        assertEquals("zhipu", payload.provider());
        assertEquals("glm-4", payload.model());
        assertEquals(812L, payload.latencyMs());
        assertEquals("stop", payload.finishReason());
        // The redacted token fields surface as unavailable rows, never as invented 0.
        assertTrue(payload.details().stream().anyMatch(row ->
                "requestedOutputTokens".equals(row.key()) && "redacted".equals(row.kind())
                        && "[redacted]".equals(row.value())));
        assertTrue(payload.details().stream().anyMatch(row ->
                "usage".equals(row.key()) && "object".equals(row.kind())));
        assertTrue(payload.details().stream().noneMatch(row -> "promptTemplateHash".equals(row.key())
                && "string".equals(row.kind())));
    }

    @Test
    void mistypedKnownKeyIsOmittedLocallyWithoutFailingTheTrace() {
        TracePayloadQuery payload = payloadOf(event("model_called", modelCalledMistypedLatency()));
        assertNull(payload.latencyMs());
        assertEquals("glm-4", payload.model());
        assertFalse(payload.details().stream().anyMatch(row -> "latencyMs".equals(row.key())));
        assertTrue(payload.details().stream().anyMatch(row -> "model".equals(row.key())));
    }

    @Test
    void unknownEventTypeKeepsOnlyThePublicSkeleton() {
        TraceEventQuery event = TraceProjectionMapper.trace(
                envelope(events(event("brand_new_event", unknownPayload())), 1)).events().get(0);
        assertEquals("brand_new_event", event.eventType());
        assertEquals("observed", event.observation());
        TracePayloadQuery payload = event.payload();
        assertNull(payload.status());
        assertTrue(payload.details().isEmpty());
    }

    @Test
    void plannerDecisionDropsInternalPolicyAndBindingStateEvenWhenPlanted() {
        TracePayloadQuery payload = payloadOf(event("task_status_changed", plannerDecision()));
        assertEquals(12, payload.nodeCount());
        assertTrue(payload.details().stream().anyMatch(row ->
                "strategy".equals(row.key()) && "stable".equals(row.value())));
        assertTrue(payload.details().stream().anyMatch(row -> "selectionReasons".equals(row.key())));
        String rendered = payload.details().stream()
                .filter(row -> "topologyAudit".equals(row.key())).findFirst().orElseThrow().value();
        assertFalse(rendered.contains("selectedBindings"));
        assertFalse(rendered.contains("bindingSearch"));
        assertFalse(rendered.contains(TraceQueryFixture.SECRET));
        assertTrue(rendered.contains("taskCount: 5"));
    }

    @Test
    void whitelistDeletesInternalReferencesAcrossFamilies() {
        TracePayloadQuery checkpoint = payloadOf(event("checkpoint_created",
                map("checkpointId", "ckpt_1", "internalState", TraceQueryFixture.SECRET)));
        assertTrue(checkpoint.details().isEmpty());
        TracePayloadQuery review = payloadOf(event("review_required", map(
                "traceRef", "trace_ref_1", "auditDecisionRef", "dec_1",
                "auditOutcome", "pending", "pendingMemory", map("outputRef", TraceQueryFixture.SECRET))));
        assertTrue(review.details().stream().anyMatch(row -> "auditOutcome".equals(row.key())));
        assertTrue(review.details().stream().noneMatch(row ->
                row.key().equals("traceRef") || row.key().equals("auditDecisionRef")
                        || row.key().equals("pendingMemory")));
        TracePayloadQuery patch = payloadOf(event("graph_patch_applied", map(
                "patchId", "patch_1", "patchRef", "patch://x", "baseGraphVersion", 2,
                "graphVersion", 3, "newRunId", "run_9")));
        assertTrue(patch.details().stream().noneMatch(row ->
                row.key().equals("patchId") || row.key().equals("patchRef")));
        assertTrue(patch.details().stream().anyMatch(row ->
                "graphVersion".equals(row.key()) && "3".equals(row.value())));
        TracePayloadQuery succeeded = payloadOf(event("step_succeeded", map(
                "commitId", "commit_1", "outputSummary", "报告已生成")));
        assertTrue(succeeded.details().stream().noneMatch(row -> "commitId".equals(row.key())));
        assertTrue(succeeded.details().stream().anyMatch(row ->
                "outputSummary".equals(row.key()) && "报告已生成".equals(row.value())));
    }

    @Test
    void fieldsByProducerBecomesTypedAssociationRowsAndNeverARawMap() {
        TracePayloadQuery payload = payloadOf(event("data_consumed", dataConsumedLedger()));
        List<TraceProducerFieldsQuery> rows = payload.producerFields();
        assertEquals(1, rows.size());
        assertEquals("step_1", rows.get(0).producerId());
        assertEquals(List.of("section", "title"), rows.get(0).fields());
        assertTrue(payload.details().stream().noneMatch(row -> "fieldsByProducer".equals(row.key())));
    }

    @Test
    void failoverResourcesKeepProducedErrorTextAndFilterNonStringRetryIds() {
        TracePayloadQuery payload = payloadOf(event("run_recovered", runRecoveredFailover()));
        assertEquals(1, payload.failedResources().size());
        assertEquals("res_1", payload.failedResources().get(0).resourceId());
        assertEquals("step_1", payload.failedResources().get(0).stepId());
        assertEquals("connection refused", payload.failedResources().get(0).error());
        assertEquals(List.of("step_1"), payload.retryStepIds());
    }

    @Test
    void brokenEnvelopeAndSkeletonFailLoudlyWithoutFakingEmptyTraces() {
        // Missing events or eventCount is a structural break, not an empty trace.
        assertThrows(IllegalArgumentException.class,
                () -> TraceProjectionMapper.trace(map(
                        "runId", "run_1", "missionId", "m", "workflowId", "w", "domain", "d",
                        "status", "completed", "eventCount", 0)));
        assertThrows(IllegalArgumentException.class,
                () -> TraceProjectionMapper.trace(map(
                        "runId", "run_1", "missionId", "m", "workflowId", "w", "domain", "d",
                        "status", "completed", "events", List.of())));
        // An empty events list with a real count is a valid terminal trace.
        assertEquals(0, TraceProjectionMapper.trace(envelope(events(), 0)).events().size());
        // Event-row skeleton damage: missing eventId, missing payload, missing createdAt.
        assertThrows(IllegalArgumentException.class, () -> TraceProjectionMapper.trace(envelope(
                events(map("runId", "run_1", "eventType", "run_completed", "observation", "",
                        "payload", Map.of(), "durationMs", 0, "createdAt", "2026-10-02T10:00:00Z")), 1)));
        assertThrows(IllegalArgumentException.class, () -> TraceProjectionMapper.trace(envelope(
                events(map("eventId", "evt_1", "runId", "run_1", "eventType", "run_completed",
                        "observation", "", "durationMs", 0, "createdAt", "2026-10-02T10:00:00Z")), 1)));
        assertThrows(IllegalArgumentException.class, () -> TraceProjectionMapper.trace(envelope(
                events(map("eventId", "evt_1", "runId", "run_1", "eventType", "run_completed",
                        "observation", "", "payload", Map.of(), "durationMs", 0)), 1)));
        // Non-object payloads and negative counters are contract breaks.
        assertThrows(IllegalArgumentException.class, () -> TraceProjectionMapper.trace(envelope(
                events(map("eventId", "evt_1", "eventType", "run_completed", "payload", "broken",
                        "durationMs", 0, "createdAt", "2026-10-02T10:00:00Z")), 1)));
        assertThrows(IllegalArgumentException.class, () -> TraceProjectionMapper.trace(map(
                "runId", "run_1", "missionId", "m", "workflowId", "w", "domain", "d",
                "status", "completed", "eventCount", -1, "events", List.of())));
    }

    @Test
    void skeletonRequiredFieldsAndDurationAreStructural() {
        Map<String, Object> missingDuration = event("run_completed", Map.of());
        missingDuration.remove("durationMs");
        assertThrows(IllegalArgumentException.class, () -> TraceProjectionMapper.trace(
                envelope(events(missingDuration), 1)));
        Map<String, Object> negativeDuration = event("run_completed", Map.of());
        negativeDuration.put("durationMs", -5);
        assertThrows(IllegalArgumentException.class, () -> TraceProjectionMapper.trace(
                envelope(events(negativeDuration), 1)));
    }

    @Test
    void largeEventCountStaysExact() {
        TraceQuery trace = TraceProjectionMapper.trace(envelope(events(), 3_000_000_000L));
        assertEquals(3_000_000_000L, trace.eventCount());
    }

    @Test
    void runtimeClassifiedKeepsAttemptIdentityAndBrokerSummaryRows() {
        TracePayloadQuery payload = payloadOf(event("runtime_event_classified", map(
                "runtimeEvent", "model.activity", "attemptId", "att_1", "sequence", 7,
                "timestamp", "2026-10-02T10:00:01Z", "payload", map("kind", "thinking"))));
        assertEquals("att_1", payload.attemptId());
        assertTrue(payload.details().stream().anyMatch(row ->
                "runtimeEvent".equals(row.key()) && "model.activity".equals(row.value())));
        assertTrue(payload.details().stream().anyMatch(row ->
                "sequence".equals(row.key()) && "7".equals(row.value()) && "number".equals(row.kind())));
    }
}
