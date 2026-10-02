package com.kinlin.ai.projection.trace;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Wire-shaped trace fixtures built from the verified producer constructions
 * (agentos_v2 export + the 26 payload families). SECRET marks values that must
 * never reach a serialized response; planted internal keys verify the whitelist
 * deletions ordered by the phase ruling.
 */
final class TraceQueryFixture {
    static final String SECRET = "SECRET-KNOWN-ONLY-TO-THE-TEST-12345";

    private static final AtomicLong SEQ = new AtomicLong();

    private TraceQueryFixture() {
    }

    static Map<String, Object> map(Object... keyValues) {
        Map<String, Object> result = new LinkedHashMap<>();
        for (int index = 0; index < keyValues.length; index += 2) {
            result.put((String) keyValues[index], keyValues[index + 1]);
        }
        return result;
    }

    static Map<String, Object> envelope(List<Map<String, Object>> events, long eventCount) {
        return map("runId", "run_1", "missionId", "mission_1", "workflowId", "wf_general",
                "domain", "general", "status", "completed", "eventCount", eventCount, "events", events);
    }

    static Map<String, Object> event(String eventType, Map<String, Object> payload) {
        Map<String, Object> event = new LinkedHashMap<>();
        event.put("eventId", "evt_" + SEQ.incrementAndGet());
        event.put("runId", "run_1");
        event.put("stepId", "step_1");
        event.put("agentName", "agent_1");
        event.put("eventType", eventType);
        event.put("observation", "observed");
        event.put("payload", payload);
        event.put("durationMs", 12);
        event.put("createdAt", "2026-10-02T10:00:00Z");
        return event;
    }

    static List<Map<String, Object>> events(Map<String, Object>... eventArray) {
        return new ArrayList<>(List.of(eventArray));
    }

    static Map<String, Object> stepScheduled() {
        return map("stepIds", List.of("step_1", "step_2"), "internalState", SECRET);
    }

    static Map<String, Object> stepSucceeded() {
        return map("commitId", "commit_1", "outputSummary", "报告已生成",
                "modelInvocations", List.of(
                        map("provider", "zhipu", "model", "glm-4", "latencyMs", 812,
                                "promptVersion", "[redacted]",
                                "usage", map("inputTokens", "[redacted]", "outputTokens", "[redacted]"))),
                "runtimeEvents", List.of(map("eventType", "model.completed")),
                "toolCalls", List.of(map("tool", "web_search", "status", "succeeded")),
                "provenanceEvents", List.of(), "communicationReads", List.of(),
                "memoryAccess", map("policyId", "pol_1", "tokenBudget", "[redacted]", "tokensUsed", 90),
                "memoryEvent", map("eventId", "mem_1", "summary", "结构化记忆", SECRET, SECRET));
    }

    static Map<String, Object> modelCalled() {
        return map("provider", "zhipu", "model", "glm-4", "latencyMs", 812,
                "requestedOutputTokens", "[redacted]", "effectiveOutputTokens", "[redacted]",
                "usage", map("input_tokens", "[redacted]", "output_tokens", "[redacted]"),
                "finishReason", "stop", "streaming", true, "callChainId", "chain_1",
                "outputPolicy", map("kind", "json"),
                "promptTemplateHash", "[redacted]");
    }

    static Map<String, Object> modelCalledMistypedLatency() {
        Map<String, Object> payload = modelCalled();
        payload.put("latencyMs", "fast");
        return payload;
    }

    static Map<String, Object> toolCalled() {
        return map("tool", "web_search", "name", "web_search", "status", "succeeded", "latencyMs", 210);
    }

    static Map<String, Object> dataConsumedLedger() {
        return map("eventId", "cons_000001", "consumerStepId", "step_2",
                "producerStepIds", List.of("step_1"), "producerEventIds", List.of("prod_000001"),
                "fieldsByProducer", map("step_1", List.of("section", "title", 42)),
                "consumedFields", List.of("section"),
                "tokensDelivered", 512, "tokensAvailable", 1024, "savingRatio", 0.5,
                "checksum", "abc", "contractStatus", "valid", "eventHash", "hash_1");
    }

    static Map<String, Object> dataConsumedMemoryAccess() {
        return map("policyId", "pol_1", "read", true, "readCount", 2, "retrievalMode", "hybrid",
                "hitRefs", List.of("mem_1"), "write", false, "written", false,
                "readTypes", List.of("report"), "writeType", "report", "limit", 4096,
                "tokenBudget", "[redacted]", "tokensUsed", 90, "requireAudit", false);
    }

    static Map<String, Object> dataProducedCapsule() {
        return map("kind", "phase_capsule", "phaseId", "phase_1", "capsuleRef", "cap_1",
                "sourceMemoryRefs", List.of("mem_1"), "evidenceRefs", List.of(),
                "tokenCount", "[redacted]");
    }

    static Map<String, Object> runtimeClassified() {
        return map("runtimeEvent", "model.activity", "attemptId", "att_1", "sequence", 7,
                "timestamp", "2026-10-02T10:00:01Z", "payload", map("kind", "thinking"));
    }

    static Map<String, Object> plannerProgress() {
        return map("planningProgress", true, "category", "planner", "stage", "outline",
                "status", "completed", "kind", "stage_completed", "attempt", 1, "retryCount", 0,
                "taskCount", 5, "dependencyCount", 4, "nodeCount", 12, "edgeCount", 15,
                "constraintCount", 3, "requiredCapabilityCount", 2, "expectedArtifactCount", 1,
                "timeoutSeconds", 300, "callKey", "call_1", "safeSummary", "ok",
                "promptAudit", List.of(map("templateHash", SECRET)),
                "profile", map("goal", SECRET),
                "selectedBindings", List.of(map("producerTaskKey", SECRET)));
    }

    static Map<String, Object> plannerDecision() {
        return map("strategy", "stable", "templateId", "tpl_1", "templateScore", 0.8,
                "thinkingMode", "enabled", "reasoningEffort", "high",
                "requestedCapabilityProfile", "legal", "effectiveCapabilityProfile", "legal",
                "capabilityProfileReason", "合同审查", "planningDiversity", "balanced",
                "planningSeed", 42, "plannerAlgorithmVersion", "v1", "candidateCount", 3,
                "selectedVariantId", "var_1", "selectedCapabilities", List.of("report_generate"),
                "selectionReasons", List.of("合同要求"), "stochasticFallback", false,
                "taskPlanVersion", 3, "taskNodeCount", 5, "nodeCount", 12, "edgeCount", 15,
                "notes", List.of("注"), "graphId", "graph_1",
                "profile", map("goal", SECRET),
                "selectedBindings", List.of(map("producerTaskKey", SECRET)),
                "promptAudit", List.of(map("templateHash", SECRET)),
                "topologyAudit", map("taskCount", 5, "semanticEdgeCount", 7, "status", "ok",
                        "selectedBindings", List.of(map("requirementId", SECRET)),
                        "bindingSearch", map("statesExplored", 3)));
    }

    static Map<String, Object> valueCleanup() {
        return map("kind", "execution_value_cleanup", "scanned", 12, "protected", 2, "deleted", 3);
    }

    static Map<String, Object> runRecoveredFailover() {
        return map("failedResources", List.of(
                        map("stepId", "step_1", "resourceId", "res_1", "error", "connection refused"),
                        "not-a-map", map("stepId", "step_9")),
                "retryStepIds", List.of("step_1", 42));
    }

    static Map<String, Object> runRecoveredCheckpoint() {
        return map("sourceRunId", "run_0", "failedStepId", "step_2",
                "reusedStepIds", List.of("step_1"), "resumeStepIds", List.of("step_2"),
                "reason", "人工重试", "mode", "successor_run");
    }

    static Map<String, Object> runFailed() {
        return map("errorCode", "MODEL_TIMEOUT", "code", "model_timeout", "message", "模型服务响应超时");
    }

    static Map<String, Object> checkpointCreated() {
        return map("checkpointId", "ckpt_1", "internalState", SECRET);
    }

    static Map<String, Object> reviewRequired() {
        return map("traceRef", "trace_ref_1", "auditDecisionRef", "dec_1",
                "auditOutcome", "pending", "pendingMemory", map("outputRef", SECRET));
    }

    static Map<String, Object> reviewDecided() {
        return map("subjectType", "step", "decision", "approved", "operationId", "op_1",
                "reviewer", "alice", "comment", "同意", "deferredMemoryDiscarded", false);
    }

    static Map<String, Object> runtimePatchApplied() {
        return map("patchType", "alternate_binding", "previousAgentId", "agent_a",
                "agentId", "agent_b", "reason", "资源切换");
    }

    static Map<String, Object> graphPatchApplied() {
        return map("patchId", "patch_1", "patchRef", "patch://x", "baseGraphVersion", 2,
                "graphVersion", 3, "newRunId", "run_9");
    }

    static Map<String, Object> unknownPayload() {
        return map("unknownKey", SECRET, "another", map("nested", SECRET));
    }
}
