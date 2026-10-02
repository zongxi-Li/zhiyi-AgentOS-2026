package com.kinlin.ai.projection.memory.mapper;

import java.util.List;
import java.util.Map;

import com.kinlin.ai.projection.memory.dto.MemoryEventItemQuery;
import com.kinlin.ai.projection.memory.dto.MemoryEventMetricsQuery;
import com.kinlin.ai.projection.memory.dto.MemoryEventsQuery;

import static com.kinlin.ai.projection.common.mapper.QueryWire.invalid;
import static com.kinlin.ai.projection.common.mapper.QueryWire.items;
import static com.kinlin.ai.projection.common.mapper.QueryWire.requiredText;
import static com.kinlin.ai.projection.common.mapper.QueryWire.text;

/**
 * Pure whitelist mapping from the agentos_v2.py {@code get_memory_events} wire to
 * typed memory DTOs. No I/O, no state, no recomputation: row order, counts and the
 * upstream redaction markers ({@code [redacted]} on capsule tokenCount) pass
 * through untouched. Unknown row kinds keep the common fields only — this endpoint
 * is polled every few seconds while a run is active, so one malformed row must not
 * destroy the whole memory view.
 */
public final class MemoryEventsProjectionMapper {
    private MemoryEventsProjectionMapper() {
    }

    private static final String KIND_ACCESS = "memory_access";
    private static final String KIND_EVENT = "memory_event";
    private static final String KIND_CAPSULE = "phase_capsule";

    public static MemoryEventsQuery memoryEvents(Map<String, Object> wire) {
        if (wire.get("items") == null) {
            throw invalid();
        }
        return new MemoryEventsQuery(
                requiredText(wire, "runId"),
                items(wire.get("items"), MemoryEventsProjectionMapper::item),
                requiredNonNegativeLong(wire, "total"));
    }

    private static MemoryEventItemQuery item(Map<?, ?> raw) {
        String kind = requiredText(raw, "kind");
        boolean access = KIND_ACCESS.equals(kind);
        boolean event = KIND_EVENT.equals(kind);
        boolean capsule = KIND_CAPSULE.equals(kind);
        return new MemoryEventItemQuery(
                kind,
                text(raw, "stepId"),
                text(raw, "createdAt"),
                access ? text(raw, "retrievalMode") : null,
                access ? strings(raw.get("hitRefs")) : null,
                access ? text(raw, "fallbackReason") : null,
                event ? text(raw, "summary") : null,
                event ? metrics(raw.get("metrics")) : null,
                capsule ? text(raw, "phaseId") : null,
                capsule ? strings(raw.get("sourceMemoryRefs")) : null,
                capsule ? text(raw, "tokenCount") : null);
    }

    private static MemoryEventMetricsQuery metrics(Object raw) {
        if (!(raw instanceof Map<?, ?> map)) {
            return null;
        }
        return new MemoryEventMetricsQuery(
                nonNegativeLong(map, "fieldCount"),
                nonNegativeLong(map, "evidenceCount"),
                nonNegativeLong(map, "modelInvocationCount"),
                nonNegativeLong(map, "toolCallCount"));
    }

    private static List<String> strings(Object raw) {
        if (raw == null) {
            return null;
        }
        if (!(raw instanceof List<?> list)) {
            throw invalid();
        }
        return list.stream()
                .filter(String.class::isInstance)
                .map(String.class::cast)
                .toList();
    }

    private static Long nonNegativeLong(Map<?, ?> source, String key) {
        if (!(source.get(key) instanceof Number value)) {
            return null;
        }
        long result = new java.math.BigDecimal(value.toString()).longValueExact();
        if (result < 0) {
            throw invalid();
        }
        return result;
    }

    private static long requiredNonNegativeLong(Map<?, ?> source, String key) {
        if (!(source.get(key) instanceof Number value)) {
            throw invalid();
        }
        long result = new java.math.BigDecimal(value.toString()).longValueExact();
        if (result < 0) {
            throw invalid();
        }
        return result;
    }
}
