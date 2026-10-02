package com.kinlin.ai.projection.trace.format;

import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * Server-side bounded display projection for trace payload objects, mirroring the
 * frontend generic-detail serializer that this DTO replaces: same depth (4), array
 * (12) and field (24) caps, same 900-char value budget, same sensitive-subkey skip
 * list, and the same "[depth limit]"/"[circular]" markers.
 *
 * <p>On top of the mirrored frontend defense, internal-policy subkeys registered by
 * the phase ruling (selectedBindings/bindingSearch, commitId/checkpointId,
 * patchId/patchRef, promptAudit/pendingMemory/profile/graphId, runtime/binding
 * state) never render even when nested inside a whitelisted structure. The output
 * is display text only; no JSON re-serialization or object passthrough happens.
 *
 * <p>This is a display-text builder, not a wire mapper: it lives outside the mapper
 * package because the recursion guard needs its scratch IdentityHashMap, which the
 * mapper no-mutation rule would otherwise reject as a false positive.
 */
public final class TraceDetailFormatter {
    private static final int MAX_DEPTH = 4;
    private static final int MAX_ARRAY_ITEMS = 12;
    private static final int MAX_OBJECT_FIELDS = 24;
    private static final int MAX_VALUE_LENGTH = 900;
    private static final int MAX_KEY_LENGTH = 72;

    private static final Pattern SENSITIVE_FIELD = Pattern.compile(
            "reason|thought|deliberation|analysis|prompt|credential|auth|cookie|password|passwd|secret|token|internal|key");

    private static final Set<String> BANNED_SUBKEYS = Set.of(
            "selectedBindings", "bindingSearch", "binding", "bindings",
            "commitId", "checkpointId", "patchId", "patchRef",
            "promptAudit", "pendingMemory", "profile", "graphId",
            "traceRef", "auditDecisionRef",
            "executionState", "executionBinding", "bindingManifest", "compiledPackage", "graphPatchRefs");

    private TraceDetailFormatter() {
    }

    public static String serialize(Object value) {
        return visit(value, 0, MAX_VALUE_LENGTH, new IdentityHashMap<>());
    }

    private static String visit(Object current, int depth, int budget, IdentityHashMap<Object, Boolean> seen) {
        if (budget <= 0) {
            return "";
        }
        if (depth > MAX_DEPTH) {
            return bounded("[depth limit]", budget);
        }
        if (current == null) {
            return "null";
        }
        if (current instanceof String text) {
            return bounded(displayText(text, Math.min(budget, MAX_VALUE_LENGTH)), budget);
        }
        if (current instanceof Number || current instanceof Boolean) {
            return bounded(String.valueOf(current), budget);
        }
        if (current instanceof Map<?, ?> || current instanceof List<?>) {
            if (depth >= MAX_DEPTH) {
                return bounded("[depth limit]", budget);
            }
            if (seen.containsKey(current)) {
                return bounded("[circular]", budget);
            }
            seen.put(current, Boolean.TRUE);
            String serialized = current instanceof List<?> list ? listBody(list, depth, budget, seen)
                    : objectBody((Map<?, ?>) current, depth, budget, seen);
            seen.remove(current);
            return serialized;
        }
        return bounded("[unsupported]", budget);
    }

    private static String listBody(List<?> list, int depth, int budget, IdentityHashMap<Object, Boolean> seen) {
        StringBuilder out = new StringBuilder("[");
        int count = Math.min(list.size(), MAX_ARRAY_ITEMS);
        for (int index = 0; index < count; index++) {
            String prefix = index > 0 ? ", " : "";
            int childBudget = budget - out.length() - prefix.length() - 2;
            if (childBudget <= 0) {
                break;
            }
            String child = visit(list.get(index), depth + 1, childBudget, seen);
            if (child.isEmpty()) {
                continue;
            }
            out.append(prefix).append(child);
        }
        if (list.size() > count && out.length() + 5 <= budget) {
            out.append(out.length() > 1 ? ", " : "").append('…');
        }
        out.append(']');
        return bounded(out.toString(), budget);
    }

    private static String objectBody(Map<?, ?> map, int depth, int budget, IdentityHashMap<Object, Boolean> seen) {
        StringBuilder out = new StringBuilder("{");
        int inspected = 0;
        for (Map.Entry<?, ?> entry : map.entrySet()) {
            if (inspected >= MAX_OBJECT_FIELDS || out.length() + 4 >= budget) {
                break;
            }
            if (!(entry.getKey() instanceof String field)) {
                continue;
            }
            inspected++;
            if (isSensitiveField(field) || BANNED_SUBKEYS.contains(field) || entry.getValue() == null) {
                continue;
            }
            String safeField = displayText(field, MAX_KEY_LENGTH);
            if (safeField.isEmpty()) {
                continue;
            }
            String prefix = out.length() > 1 ? ", " : "";
            int entryBudget = budget - out.length() - prefix.length() - safeField.length() - 4;
            String safeValue = visit(entry.getValue(), depth + 1, entryBudget, seen);
            if (safeValue.isEmpty()) {
                continue;
            }
            String item = prefix + safeField + ": " + safeValue;
            if (out.length() + item.length() + 1 > budget) {
                break;
            }
            out.append(item);
        }
        out.append('}');
        return bounded(out.toString(), budget);
    }

    private static boolean isSensitiveField(String field) {
        String normalized = field.replaceAll("[^a-zA-Z0-9]", "").toLowerCase();
        return !normalized.isEmpty() && SENSITIVE_FIELD.matcher(normalized).find();
    }

    private static String displayText(String value, int maxLength) {
        String normalized = value.trim();
        if (normalized.length() > maxLength) {
            return normalized.substring(0, Math.max(0, maxLength - 1)) + "…";
        }
        return normalized;
    }

    private static String bounded(String output, int budget) {
        if (output.length() <= budget) {
            return output;
        }
        return budget > 0 ? output.substring(0, budget - 1) + "…" : "";
    }
}
