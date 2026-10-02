package com.kinlin.ai.projection.resource;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Minimal sanitized GET /runs/{id}/resource-usage wire fixtures mirroring the upstream
 * agentos_v2.py {@code get_resource_usage} dict exactly: every listed key is present on the
 * wire (nulls included), because this endpoint is a plain dict return, not an exclude_none
 * pydantic dump.
 *
 * <p>Two upstream paths: observed usage from real model calls, and the zero-call state where
 * the capability comes from the declared catalog hint (provider OR model only). SECRET
 * sentinels mark values the projection must drop: the whole scheduler object, the capability
 * subkeys without a reader (maxTokensField/features/maxTokensRequired/observedAt), and any
 * unknown wire key.
 */
public final class ResourceUsageQueryFixture {
    public static final String SECRET = "internal-control-sentinel";

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
}
