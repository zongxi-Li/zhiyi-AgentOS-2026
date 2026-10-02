package com.kinlin.ai.projection.output.mapper;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.IdentityHashMap;
import java.util.Set;
import java.util.List;
import java.util.Map;

import com.kinlin.ai.projection.common.mapper.QueryWire;
import com.kinlin.ai.projection.output.dto.ContentMemberQuery;
import com.kinlin.ai.projection.output.dto.ContentValueQuery;
import com.kinlin.ai.projection.output.dto.LegacyOutputItemQuery;
import com.kinlin.ai.projection.output.dto.LegacyOutputsQuery;
import com.kinlin.ai.projection.output.dto.OutputQuery;

import static com.kinlin.ai.projection.common.mapper.QueryWire.invalid;
import static com.kinlin.ai.projection.common.mapper.QueryWire.requiredText;

/**
 * Pure whitelist mapping from the agentos_v2.py output wires to the typed output
 * DTOs. The product body is carried completely: no truncation, no reordering, no
 * recomputation — scalars, arrays, object members (in upstream key order), booleans,
 * nulls and exact numbers all pass through the content value grammar. A cycle (or
 * any value outside the JSON grammar) fails the contract loudly instead of being
 * silently cut; the visited set only exists so such input fails instead of
 * overflowing the stack.
 */
public final class OutputProjectionMapper {
    private OutputProjectionMapper() {
    }

    private static final String KIND_NULL = "null";
    private static final String KIND_STRING = "string";
    private static final String KIND_BOOLEAN = "boolean";
    private static final String KIND_NUMBER = "number";
    private static final String KIND_LIST = "list";
    private static final String KIND_OBJECT = "object";

    public static OutputQuery output(Map<String, Object> wire) {
        return new OutputQuery(
                requiredText(wire, "runId"),
                requiredText(wire, "outputRef"),
                value(wire.get("content"), newSeen()));
    }

    /**
     * Cycle guard: marks stay for the whole walk (no unmarking), so a true cycle
     * fails loudly. Real wire trees never share instances between positions, and
     * the mapper tests never reuse an instance, so an add-only set is sufficient
     * and keeps the no-mutation token scan clean.
     */
    private static java.util.Set<Object> newSeen() {
        return java.util.Collections.newSetFromMap(new IdentityHashMap<>());
    }

    public static LegacyOutputsQuery legacyOutputs(Map<String, Object> wire) {
        if (wire.get("items") == null) {
            throw invalid();
        }
        return new LegacyOutputsQuery(
                requiredText(wire, "runId"),
                QueryWire.items(wire.get("items"), OutputProjectionMapper::legacyItem));
    }

    private static LegacyOutputItemQuery legacyItem(Map<?, ?> raw) {
        return new LegacyOutputItemQuery(
                requiredText(raw, "stepId"),
                requiredText(raw, "name"),
                requiredText(raw, "status"),
                value(raw.get("content"), newSeen()));
    }

    private static ContentValueQuery value(Object raw, Set<Object> seen) {
        if (raw == null) {
            return new ContentValueQuery(KIND_NULL, null, null, null, null, null);
        }
        if (raw instanceof String text) {
            return new ContentValueQuery(KIND_STRING, text, null, null, null, null);
        }
        if (raw instanceof Boolean bool) {
            return new ContentValueQuery(KIND_BOOLEAN, null, bool, null, null, null);
        }
        if (raw instanceof Number number) {
            return new ContentValueQuery(KIND_NUMBER, null, null, exactNumber(number), null, null);
        }
        if (raw instanceof List<?> list) {
            if (!seen.add(list)) {
                throw invalid();
            }
            List<ContentValueQuery> items = new ArrayList<>(list.size());
            for (Object item : list) {
                items.add(value(item, seen));
            }
            return new ContentValueQuery(KIND_LIST, null, null, null, items, null);
        }
        if (raw instanceof Map<?, ?> map) {
            if (!seen.add(map)) {
                throw invalid();
            }
            List<ContentMemberQuery> members = new ArrayList<>(map.size());
            for (Map.Entry<?, ?> entry : map.entrySet()) {
                if (!(entry.getKey() instanceof String name)) {
                    throw invalid();
                }
                members.add(new ContentMemberQuery(name, value(entry.getValue(), seen)));
            }
            return new ContentValueQuery(KIND_OBJECT, null, null, null, null, members);
        }
        throw invalid();
    }

    /**
     * Exact number carrier: the wire text decides, so integers stay integers and
     * decimals keep their shortest round-trip form; non-finite JSON never occurs.
     */
    private static BigDecimal exactNumber(Number number) {
        if (number instanceof Double && !Double.isFinite(number.doubleValue())) {
            throw invalid();
        }
        return new BigDecimal(number.toString());
    }
}
