package com.kinlin.ai.projection.resource;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Minimal sanitized resource-usage wire fixtures (GET /runs/{id}/resource-usage and
 * /resource-usage/calls) mirroring the upstream agentos_v2.py dict returns exactly: every
 * listed key is present on the wire (nulls included), because these endpoints are plain
 * dict returns, not an exclude_none pydantic dump.
 *
 * <p>Overview paths: observed usage from real model calls, and the zero-call state where
 * the capability comes from the declared catalog hint (provider OR model only). Calls paths:
 * a mid-run page (traceable cursor arithmetic), the last page, and an empty filter result.
 * SECRET sentinels mark values the projection must drop: the whole scheduler object, the
 * capability subkeys without a reader (maxTokensField/features/maxTokensRequired/observedAt),
 * the per-call capability dict, and any unknown wire key.
 */
public final class ResourceUsageQueryFixture {
    public static final String SECRET = "internal-control-sentinel";
    public static final String TIME = "2026-10-02T09:00:01.234567+08:00";

    private ResourceUsageQueryFixture() { }

    /** Observed path: two aggregated model calls, capability from the last call audit. */
    public static Map<String, Object> observedUsage() {
        Map<String, Object> capability = new LinkedHashMap<>();
        capability.put("provider", "zhipu");
        capability.put("model", "glm-4.7");
        capability.put("version", "v1");
        capability.put("revision", "r2");
        capability.put("source", "provider_reported");
        capability.put("contextWindowTokens", 200000);
        capability.put("maxOutputTokens", 98304);
        capability.put("maxTokensField", SECRET);
        capability.put("maxTokensRequired", true);
        capability.put("features", Map.of("promptCaching", true, "internalFeature", SECRET));
        capability.put("observedAt", SECRET);
        Map<String, Object> usage = new LinkedHashMap<>();
        usage.put("inputTokens", 12300);
        usage.put("outputTokens", 4520);
        usage.put("cacheReadTokens", 3100);
        usage.put("cacheWriteTokens", 512);
        usage.put("reasoningTokens", 890);
        usage.put("totalTokens", 16820);
        usage.put("callCount", 2);
        usage.put("retryCount", 1);
        usage.put("latencyMs", 5120);
        usage.put("cacheHitRatio", 0.252);
        Map<String, Object> pressure = new LinkedHashMap<>();
        pressure.put("current", 0.5);
        pressure.put("peak", 0.75);
        pressure.put("currentInputTokens", 10000);
        pressure.put("peakInputTokens", 15000);
        pressure.put("contextWindowTokens", 200000);
        pressure.put("source", "usage_derived");
        Map<String, Object> composition = new LinkedHashMap<>();
        composition.put("materialManifestCount", 2);
        composition.put("materialFragmentCount", 7);
        composition.put("taskCount", 5);
        composition.put("completedTaskCount", 3);
        composition.put("persistedResultFragmentCount", 4);
        composition.put("reducerManifestCount", 1);
        composition.put("chapterCount", 9);
        composition.put("artifactCount", 1);
        composition.put("assemblyComplete", false);
        composition.put("taskProgress", 0.6);
        return envelope(capability, "observed", "api_controlled", usage, pressure, composition);
    }

    /** Zero-call path: catalog hint (provider only, no model), unobserved pressure, zero totals. */
    public static Map<String, Object> declaredZeroCallUsage() {
        Map<String, Object> capability = new LinkedHashMap<>();
        capability.put("provider", "zhipu");
        capability.put("source", "adapter_declared");
        capability.put("contextWindowTokens", 131072);
        capability.put("maxTokensRequired", false);
        capability.put("features", Map.of());
        Map<String, Object> usage = new LinkedHashMap<>();
        for (String key : new String[] {"inputTokens", "outputTokens", "cacheReadTokens",
                "cacheWriteTokens", "reasoningTokens", "totalTokens"}) {
            usage.put(key, 0);
        }
        usage.put("callCount", 0);
        usage.put("retryCount", 0);
        usage.put("latencyMs", 0);
        usage.put("cacheHitRatio", null);
        Map<String, Object> pressure = new LinkedHashMap<>();
        pressure.put("current", null);
        pressure.put("peak", null);
        pressure.put("currentInputTokens", null);
        pressure.put("peakInputTokens", null);
        pressure.put("contextWindowTokens", 131072);
        pressure.put("source", "capability_declared");
        Map<String, Object> composition = new LinkedHashMap<>();
        for (String key : new String[] {"materialManifestCount", "materialFragmentCount", "taskCount",
                "completedTaskCount", "persistedResultFragmentCount", "reducerManifestCount",
                "chapterCount", "artifactCount"}) {
            composition.put(key, 0);
        }
        composition.put("assemblyComplete", false);
        composition.put("taskProgress", null);
        return envelope(capability, "declared", "catalog_default", usage, pressure, composition);
    }

    private static Map<String, Object> envelope(Map<String, Object> capability, String capabilitySource,
            String outputPolicy, Map<String, Object> usage, Map<String, Object> pressure,
            Map<String, Object> composition) {
        Map<String, Object> wire = new LinkedHashMap<>();
        wire.put("runId", "run_1");
        wire.put("capability", capability);
        wire.put("capabilitySource", capabilitySource);
        wire.put("outputPolicy", outputPolicy);
        wire.put("usage", usage);
        wire.put("contextPressure", pressure);
        wire.put("composition", composition);
        // No frontend consumer; the mapper must drop the whole object, not rename its state.
        wire.put("scheduler", Map.of("activeSlots", 2, "queueDepth", 1, "checkpointCount", 1,
                "recoveryCount", SECRET));
        // Unknown internal key must not survive the whitelist either.
        wire.put("internalSchedulerState", SECRET);
        return wire;
    }

    /**
     * First calls page of a 25-call run queried with pageSize=2 (traceable upstream cursor
     * arithmetic: nextCursor = start + pageSize = "2"). Row capability dicts are dropped by
     * the mapper, so their SECRET payload must not echo.
     */
    public static Map<String, Object> firstCallPage() {
        Map<String, Object> fullUsage = new LinkedHashMap<>();
        fullUsage.put("inputTokens", 9800);
        fullUsage.put("outputTokens", 2400);
        fullUsage.put("cacheReadTokens", 2100);
        fullUsage.put("cacheWriteTokens", 256);
        fullUsage.put("reasoningTokens", 460);
        fullUsage.put("totalTokens", 12200);
        Map<String, Object> full = new LinkedHashMap<>();
        full.put("callId", "trace_001");
        full.put("stepId", "step_outline");
        full.put("provider", "zhipu");
        full.put("model", "glm-4.7");
        full.put("createdAt", TIME);
        full.put("latencyMs", 1234);
        full.put("usage", fullUsage);
        full.put("finishReason", "stop");
        full.put("outputPolicy", "api_controlled");
        full.put("requestedOutputTokens", 98304);
        full.put("effectiveOutputTokens", 8192);
        full.put("effectiveReason", "provider_default");
        full.put("outputExhausted", false);
        full.put("partIndex", 1);
        full.put("callChainId", "chain_a1");
        full.put("contextPressure", 0.5);
        full.put("capability", Map.of("provider", "zhipu", "model", "glm-4.7", "internal", SECRET));
        // Error-path audit shape: usage empty, optional keys absent, exhausted retry.
        Map<String, Object> zeroUsage = new LinkedHashMap<>();
        for (String key : new String[] {"inputTokens", "outputTokens", "cacheReadTokens",
                "cacheWriteTokens", "reasoningTokens", "totalTokens"}) {
            zeroUsage.put(key, 0);
        }
        Map<String, Object> exhausted = new LinkedHashMap<>();
        exhausted.put("callId", "trace_002");
        exhausted.put("stepId", null);
        exhausted.put("provider", null);
        exhausted.put("model", null);
        exhausted.put("createdAt", TIME);
        exhausted.put("latencyMs", 40);
        exhausted.put("usage", zeroUsage);
        exhausted.put("finishReason", null);
        exhausted.put("outputPolicy", "provider_required");
        exhausted.put("requestedOutputTokens", null);
        exhausted.put("effectiveOutputTokens", null);
        exhausted.put("effectiveReason", null);
        exhausted.put("outputExhausted", true);
        exhausted.put("partIndex", null);
        exhausted.put("callChainId", null);
        exhausted.put("contextPressure", null);
        exhausted.put("capability", null);
        Map<String, Object> page = new LinkedHashMap<>();
        page.put("runId", "run_1");
        page.put("items", List.of(full, exhausted));
        page.put("nextCursor", "2");
        page.put("total", 25);
        return page;
    }

    /** Last page: one item, no cursor (start + pageSize == total). */
    public static Map<String, Object> lastCallPage() {
        Map<String, Object> row = new LinkedHashMap<>((Map<String, Object>) ((List<?>) firstCallPage().get("items")).get(0));
        row.put("callId", "trace_025");
        Map<String, Object> page = new LinkedHashMap<>();
        page.put("runId", "run_1");
        page.put("items", List.of(row));
        page.put("nextCursor", null);
        page.put("total", 25);
        return page;
    }

    /** stepId filter with zero matches: empty page with total 0, no cursor. */
    public static Map<String, Object> emptyCallPage() {
        Map<String, Object> page = new LinkedHashMap<>();
        page.put("runId", "run_1");
        page.put("items", List.of());
        page.put("nextCursor", null);
        page.put("total", 0);
        return page;
    }
}
