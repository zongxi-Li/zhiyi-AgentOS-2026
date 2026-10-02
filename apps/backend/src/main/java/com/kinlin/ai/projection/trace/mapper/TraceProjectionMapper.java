package com.kinlin.ai.projection.trace.mapper;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.kinlin.ai.projection.common.mapper.QueryWire;
import com.kinlin.ai.projection.trace.dto.TraceEventQuery;
import com.kinlin.ai.projection.trace.dto.TraceFailedResourceQuery;
import com.kinlin.ai.projection.trace.dto.TracePayloadQuery;
import com.kinlin.ai.projection.trace.dto.TraceProducerFieldsQuery;
import com.kinlin.ai.projection.trace.dto.TracePublicDetailQuery;
import com.kinlin.ai.projection.trace.dto.TraceQuery;
import com.kinlin.ai.projection.trace.format.TraceDetailFormatter;

import static com.kinlin.ai.projection.common.mapper.QueryWire.invalid;
import static com.kinlin.ai.projection.common.mapper.QueryWire.items;
import static com.kinlin.ai.projection.common.mapper.QueryWire.object;
import static com.kinlin.ai.projection.common.mapper.QueryWire.requiredText;

/**
 * Pure whitelist mapping from the agentos_v2.py {@code get_trace} wire to typed
 * trace DTOs. No I/O, no state, no upstream mutation, no recomputation: the event
 * order stays the upstream (createdAt, eventId) order, {@code eventCount} stays the
 * full persisted count (the workspace view legitimately yields
 * {@code eventCount > events.size()}), and the {@code view} parameter is forwarded
 * untouched by the controller.
 *
 * <p>Public-surface rules (phase ruling 4.1): every payload key must be approved by
 * its event-family whitelist <em>with the expected wire kind</em>; unknown keys are
 * omitted, mistyped known keys are locally omitted (never echoed, not even through a
 * display row), and unknown or historical event types keep only the public skeleton.
 * The upstream {@code [redacted]} / {@code [truncated]} markers surface as explicit
 * unavailable detail rows instead of invented numbers. Internal policy
 * (promptAudit/profile/selectedBindings/pendingMemory), internal references
 * (commitId/checkpointId/patchId/patchRef/graphId/traceRef/auditDecisionRef) and
 * runtime binding state have no whitelist entry and cannot reach the wire —
 * including through nested objects, which {@link TraceDetailFormatter} re-filters
 * while formatting display text.
 */
public final class TraceProjectionMapper {
    private TraceProjectionMapper() {
    }

    private static final String REDACTED_MARKER = "[redacted]";
    private static final String TRUNCATED_MARKER = "[truncated]";

    /** Detail spec: a whitelisted payload key and its expected wire kind. */
    private record DetailSpec(String key, String kind) {
        static DetailSpec of(String encoded) {
            int split = encoded.indexOf(':');
            if (split <= 0 || split == encoded.length() - 1) {
                throw new IllegalStateException("malformed trace family spec: " + encoded);
            }
            return new DetailSpec(encoded.substring(0, split), encoded.substring(split + 1));
        }
    }

    /** The dynamic producer→fields association is projected to typed rows, never displayed raw. */
    private static final String FIELDS_BY_PRODUCER = "fieldsByProducer";

    /**
     * Planner/task-status family keys (workflow_runtime.py _PLANNER_PROGRESS_FIELDS
     * + draft/parsed node/edge projections + topology audit + plugin scope + the
     * planner decision whitelist with its banned internal keys removed).
     */
    private static final String PLANNER_KEYS = "planningProgress:boolean,category:string,stage:string,"
            + "status:string,attempt:number,retryCount:number,timeoutSeconds:number,errorCode:string,"
            + "kind:string,taskCount:number,dependencyCount:number,nodeCount:number,"
            + "edgeCount:number,constraintCount:number,requiredCapabilityCount:number,"
            + "expectedArtifactCount:number,callKey:string,retryIndex:number,elapsedMs:number,"
            + "idleMs:number,receivedChunks:number,receivedLength:number,safeSummary:string,"
            + "delta:string,nodes:list,edges:list,relations:list,topologyAudit:object,"
            + "resolvedEnabledPluginIds:list,pluginSnapshot:list,capabilityCatalogRevision:number,"
            + "visibleCapabilityCount:number,scopeExcludedAgentCount:number,"
            + "resolutionPolicy:string,strategy:string,templateId:string,templateScore:number,"
            + "thinkingMode:string,reasoningEffort:string,requestedCapabilityProfile:string,"
            + "effectiveCapabilityProfile:string,capabilityProfileReason:string,"
            + "planningDiversity:string,planningSeed:number,plannerAlgorithmVersion:string,"
            + "candidateCount:number,selectedVariantId:string,selectedCapabilities:list,"
            + "selectionReasons:list,stochasticFallback:boolean,taskPlanVersion:number,"
            + "taskNodeCount:number,notes:list,scanned:number,protected:number,deleted:number";

    /**
     * The finite per-event-family public key whitelist, in display order, with the
     * expected wire kind per key. Keys are evidence-backed from the producer
     * construction sites; families not listed here (including every unknown or
     * future event type) approve nothing.
     */
    private static final Map<String, List<DetailSpec>> FAMILIES = buildFamilies();

    private static Map<String, List<DetailSpec>> buildFamilies() {
        // Collectors.toMap into a LinkedHashMap keeps the registered display order;
        // the mapper no-mutation rule bans literal map writes in this package.
        return Collections.unmodifiableMap(java.util.stream.Stream.of(
                java.util.Map.entry("step_scheduled", specs("stepIds:list")),
                java.util.Map.entry("step_succeeded", specs(
                        "outputSummary:string", "modelInvocations:list", "runtimeEvents:list",
                        "toolCalls:list", "provenanceEvents:list", "communicationReads:list",
                        "memoryAccess:object", "memoryEvent:object")),
                java.util.Map.entry("model_called", specs(
                        "provider:string", "model:string", "latencyMs:number",
                        "promptVersion:string", "promptTemplateHash:string", "promptInstanceHash:string",
                        "stablePrefixHash:string", "schemaHash:string", "kernelVersion:string",
                        "preset:string", "presetVersion:string", "capabilityId:string",
                        "capabilityPolicyVersion:string", "requestProtocolVersion:string",
                        "outputProtocolVersion:string", "promptRendererVersion:string", "requestType:string",
                        "providerFamily:string", "modelVersion:string", "streaming:boolean",
                        "trustSummary:object", "usage:object", "finishReason:string",
                        "capability:object", "outputPolicy:object",
                        "requestedOutputTokens:number", "effectiveOutputTokens:number",
                        "effectiveReason:string", "outputExhausted:boolean", "partIndex:number",
                        "callChainId:string")),
                java.util.Map.entry("tool_called", specs(
                        "tool:string", "name:string", "status:string", "latencyMs:number", "errorCode:string")),
                java.util.Map.entry("data_consumed", specs(
                        "policyId:string", "read:boolean", "readCount:number", "retrievalMode:string",
                        "hitRefs:list", "write:boolean", "written:boolean", "readTypes:list",
                        "writeType:string", "limit:number", "tokenBudget:number", "tokensUsed:number",
                        "requireAudit:boolean",
                        "runId:string", "consumerStepId:string", "producerStepId:string",
                        "outputRef:string", "fields:list", "tokens:number", "channel:string",
                        "eventId:string", "producerStepIds:list", "producerEventIds:list",
                        "fieldsByProducer:object", "consumedFields:list", "tokensDelivered:number",
                        "tokensAvailable:number", "savingRatio:number", "checksum:string",
                        "contractStatus:string", "eventHash:string", "interactionId:string",
                        "evidenceRefs:list")),
                java.util.Map.entry("data_produced", specs(
                        "eventId:string", "producerStepId:string", "fieldNames:list", "checksum:string",
                        "tokenSize:number", "evidenceRefs:list", "eventHash:string",
                        "runId:string", "stepId:string", "summary:string", "metrics:object",
                        "decision:object", "relations:object",
                        "kind:string", "phaseId:string", "capsuleRef:string",
                        "sourceMemoryRefs:list", "tokenCount:number")),
                java.util.Map.entry("runtime_event_classified", specs(
                        "runtimeEvent:string", "attemptId:string", "sequence:number",
                        "timestamp:string", "payload:object")),
                java.util.Map.entry("task_status_changed", specs(PLANNER_KEYS.split(","))),
                java.util.Map.entry("stochastic_planning_fallback", specs(PLANNER_KEYS.split(","))),
                java.util.Map.entry("run_recovered", specs(
                        "failedResources:list", "retryStepIds:list", "sourceRunId:string",
                        "failedStepId:string", "reusedStepIds:list", "resumeStepIds:list",
                        "reason:string", "mode:string")),
                java.util.Map.entry("run_failed", specs("errorCode:string", "code:string", "message:string")),
                java.util.Map.entry("run_completed", specs()),
                java.util.Map.entry("run_cancelled", specs()),
                java.util.Map.entry("checkpoint_created", specs()),
                java.util.Map.entry("step_failed", specs()),
                java.util.Map.entry("step_started", specs()),
                java.util.Map.entry("run_started", specs()),
                java.util.Map.entry("review_required", specs("auditOutcome:string")),
                java.util.Map.entry("review_decided", specs(
                        "subjectType:string", "decision:string", "operationId:string", "reviewer:string",
                        "comment:string", "deferredMemoryDiscarded:boolean", "runId:string",
                        "stepId:string", "expectedRunUpdatedAt:string", "expectedStepStatus:string")),
                java.util.Map.entry("runtime_patch_applied", specs(
                        "patchType:string", "previousAgentId:string", "agentId:string", "reason:string")),
                java.util.Map.entry("graph_patch_applied", specs(
                        "baseGraphVersion:number", "graphVersion:number", "newRunId:string")))
                .collect(java.util.stream.Collectors.toMap(java.util.Map.Entry::getKey,
                        java.util.Map.Entry::getValue,
                        (left, right) -> { throw new IllegalStateException("duplicate trace family"); },
                        LinkedHashMap::new)));
    }

    private static List<DetailSpec> specs(String... encoded) {
        List<DetailSpec> parsed = new ArrayList<>();
        for (String entry : encoded) {
            parsed.add(DetailSpec.of(entry.trim()));
        }
        return List.copyOf(parsed);
    }

    private static boolean approved(List<DetailSpec> family, String key, String kind) {
        for (DetailSpec spec : family) {
            if (spec.key().equals(key)) {
                return spec.kind().equals(kind);
            }
        }
        return false;
    }

    public static TraceQuery trace(Map<String, Object> wire) {
        if (wire.get("events") == null || wire.get("eventCount") == null) {
            throw invalid();
        }
        return new TraceQuery(
                requiredText(wire, "runId"),
                QueryWire.text(wire, "missionId"),
                QueryWire.text(wire, "workflowId"),
                QueryWire.text(wire, "domain"),
                requiredText(wire, "status"),
                requiredNonNegativeLong(wire, "eventCount"),
                items(wire.get("events"), TraceProjectionMapper::event));
    }

    private static TraceEventQuery event(Map<?, ?> raw) {
        if (raw.get("payload") == null) {
            throw invalid();
        }
        String eventType = requiredText(raw, "eventType");
        return new TraceEventQuery(
                requiredText(raw, "eventId"),
                QueryWire.text(raw, "runId"),
                QueryWire.text(raw, "stepId"),
                QueryWire.text(raw, "agentName"),
                eventType,
                QueryWire.text(raw, "observation"),
                requiredNonNegativeLong(raw, "durationMs"),
                requiredText(raw, "createdAt"),
                payload(object(raw.get("payload")), FAMILIES.getOrDefault(eventType, List.of())));
    }

    private static TracePayloadQuery payload(Map<?, ?> raw, List<DetailSpec> family) {
        return new TracePayloadQuery(
                field(raw, family, "status", "string") ? textOrOmit(raw, "status") : null,
                field(raw, family, "tool", "string") ? textOrOmit(raw, "tool") : null,
                field(raw, family, "name", "string") ? textOrOmit(raw, "name") : null,
                field(raw, family, "model", "string") ? textOrOmit(raw, "model") : null,
                field(raw, family, "provider", "string") ? textOrOmit(raw, "provider") : null,
                field(raw, family, "finishReason", "string") ? textOrOmit(raw, "finishReason") : null,
                field(raw, family, "latencyMs", "number") ? exactLong(raw, "latencyMs") : null,
                field(raw, family, "producerStepId", "string") ? textOrOmit(raw, "producerStepId") : null,
                field(raw, family, "producerStepIds", "list") ? strings(raw.get("producerStepIds")) : null,
                field(raw, family, "consumerStepId", "string") ? textOrOmit(raw, "consumerStepId") : null,
                field(raw, family, "interactionId", "string") ? textOrOmit(raw, "interactionId") : null,
                field(raw, family, "outputRef", "string") ? textOrOmit(raw, "outputRef") : null,
                field(raw, family, "channel", "string") ? textOrOmit(raw, "channel") : null,
                field(raw, family, "fields", "list") ? strings(raw.get("fields")) : null,
                field(raw, family, "consumedFields", "list") ? strings(raw.get("consumedFields")) : null,
                field(raw, family, FIELDS_BY_PRODUCER, "object")
                        ? producerFields(raw.get(FIELDS_BY_PRODUCER)) : null,
                field(raw, family, "tokens", "number") ? exactLong(raw, "tokens") : null,
                field(raw, family, "tokensDelivered", "number") ? exactLong(raw, "tokensDelivered") : null,
                field(raw, family, "contractStatus", "string") ? textOrOmit(raw, "contractStatus") : null,
                field(raw, family, "errorCode", "string") ? textOrOmit(raw, "errorCode") : null,
                field(raw, family, "code", "string") ? textOrOmit(raw, "code") : null,
                field(raw, family, "message", "string") ? textOrOmit(raw, "message") : null,
                field(raw, family, "summary", "string") ? textOrOmit(raw, "summary") : null,
                field(raw, family, "reason", "string") ? textOrOmit(raw, "reason") : null,
                field(raw, family, "graphVersion", "number") ? exactLong(raw, "graphVersion") : null,
                field(raw, family, "attemptId", "string") ? textOrOmit(raw, "attemptId") : null,
                field(raw, family, "planningProgress", "boolean") ? boolOrOmit(raw, "planningProgress") : null,
                field(raw, family, "category", "string") ? textOrOmit(raw, "category") : null,
                field(raw, family, "stage", "string") ? textOrOmit(raw, "stage") : null,
                field(raw, family, "kind", "string") ? textOrOmit(raw, "kind") : null,
                field(raw, family, "attempt", "number") ? smallInteger(raw, "attempt") : null,
                field(raw, family, "retryCount", "number") ? smallInteger(raw, "retryCount") : null,
                field(raw, family, "taskCount", "number") ? smallInteger(raw, "taskCount") : null,
                field(raw, family, "dependencyCount", "number") ? smallInteger(raw, "dependencyCount") : null,
                field(raw, family, "nodeCount", "number") ? smallInteger(raw, "nodeCount") : null,
                field(raw, family, "edgeCount", "number") ? smallInteger(raw, "edgeCount") : null,
                field(raw, family, "constraintCount", "number") ? smallInteger(raw, "constraintCount") : null,
                field(raw, family, "requiredCapabilityCount", "number")
                        ? smallInteger(raw, "requiredCapabilityCount") : null,
                field(raw, family, "expectedArtifactCount", "number")
                        ? smallInteger(raw, "expectedArtifactCount") : null,
                field(raw, family, "timeoutSeconds", "number") ? smallInteger(raw, "timeoutSeconds") : null,
                field(raw, family, "failedResources", "list") ? failedResources(raw.get("failedResources")) : null,
                field(raw, family, "retryStepIds", "list") ? strings(raw.get("retryStepIds")) : null,
                details(raw, family));
    }

    private static boolean field(Map<?, ?> raw, List<DetailSpec> family, String key, String kind) {
        return approved(family, key, kind) && raw.get(key) != null;
    }

    private static List<TracePublicDetailQuery> details(Map<?, ?> raw, List<DetailSpec> family) {
        List<TracePublicDetailQuery> rows = new ArrayList<>();
        for (DetailSpec spec : family) {
            if (FIELDS_BY_PRODUCER.equals(spec.key())) {
                continue;
            }
            Object value = raw.get(spec.key());
            if (value == null) {
                continue;
            }
            String kind = rowKind(spec.kind(), value);
            if (kind == null) {
                continue;
            }
            String display = TraceDetailFormatter.serialize(value);
            if (display.isEmpty()) {
                continue;
            }
            rows.add(new TracePublicDetailQuery(spec.key(), display, kind));
        }
        return rows;
    }

    /**
     * The display kind of one whitelisted value: the upstream unavailable markers
     * win (they arrive as strings in place of the expected type), a matching wire
     * kind renders under the registered kind, and a mistyped known key renders
     * nothing — the original object is never echoed.
     */
    private static String rowKind(String expected, Object value) {
        if (REDACTED_MARKER.equals(value)) {
            return "redacted";
        }
        if (TRUNCATED_MARKER.equals(value)) {
            return "truncated";
        }
        return switch (expected) {
            case "string" -> value instanceof String ? "string" : null;
            case "number" -> value instanceof Number ? "number" : null;
            case "boolean" -> value instanceof Boolean ? "boolean" : null;
            case "list" -> value instanceof List ? "list" : null;
            case "object" -> value instanceof Map ? "object" : null;
            default -> null;
        };
    }

    private static List<TraceProducerFieldsQuery> producerFields(Object raw) {
        if (!(raw instanceof Map<?, ?> map)) {
            return null;
        }
        List<TraceProducerFieldsQuery> rows = new ArrayList<>();
        for (Map.Entry<?, ?> entry : map.entrySet()) {
            if (!(entry.getKey() instanceof String producerId) || producerId.isBlank()
                    || !(entry.getValue() instanceof List<?> fields)) {
                continue;
            }
            List<String> safeFields = strings(fields);
            if (safeFields.isEmpty()) {
                continue;
            }
            rows.add(new TraceProducerFieldsQuery(producerId, safeFields));
        }
        return rows.isEmpty() ? null : rows;
    }

    private static List<TraceFailedResourceQuery> failedResources(Object raw) {
        if (!(raw instanceof List<?> list)) {
            return null;
        }
        List<TraceFailedResourceQuery> rows = new ArrayList<>();
        for (Object item : list) {
            if (!(item instanceof Map<?, ?> entry)) {
                continue;
            }
            String resourceId = textOrOmit(entry, "resourceId");
            if (resourceId == null) {
                continue;
            }
            rows.add(new TraceFailedResourceQuery(textOrOmit(entry, "stepId"), resourceId,
                    textOrOmit(entry, "error")));
        }
        return rows.isEmpty() ? null : rows;
    }

    private static List<String> strings(Object raw) {
        if (!(raw instanceof List<?> list)) {
            return null;
        }
        return strings(list);
    }

    private static List<String> strings(List<?> list) {
        List<String> result = new ArrayList<>();
        for (Object item : list) {
            if (item instanceof String value) {
                result.add(value);
            }
        }
        return result;
    }

    /** Tolerant scalar readers: a mistyped known key is omitted, never echoed or fatal. */
    private static String textOrOmit(Map<?, ?> source, String key) {
        return source.get(key) instanceof String value ? value : null;
    }

    private static Boolean boolOrOmit(Map<?, ?> source, String key) {
        return source.get(key) instanceof Boolean value ? value : null;
    }

    private static Long exactLong(Map<?, ?> source, String key) {
        if (!(source.get(key) instanceof Number value)) {
            return null;
        }
        BigDecimal exact = value instanceof Float || value instanceof Double
                ? new BigDecimal(value.doubleValue()) : new BigDecimal(value.toString());
        try {
            return exact.longValueExact();
        } catch (ArithmeticException drift) {
            return null;
        }
    }

    private static Integer smallInteger(Map<?, ?> source, String key) {
        Long value = exactLong(source, key);
        if (value == null) {
            return null;
        }
        try {
            return Math.toIntExact(value);
        } catch (ArithmeticException overflow) {
            return null;
        }
    }

    private static long requiredNonNegativeLong(Map<?, ?> source, String key) {
        if (!(source.get(key) instanceof Number value)) {
            throw invalid();
        }
        BigDecimal exact = value instanceof Float || value instanceof Double
                ? new BigDecimal(value.doubleValue()) : new BigDecimal(value.toString());
        long result = exact.longValueExact();
        if (result < 0) {
            throw invalid();
        }
        return result;
    }
}
