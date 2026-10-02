package com.kinlin.ai.projection.resource.mapper;

import java.math.BigDecimal;
import java.util.Map;

import com.kinlin.ai.projection.resource.dto.CompositionQuery;
import com.kinlin.ai.projection.resource.dto.ContextPressureQuery;
import com.kinlin.ai.projection.resource.dto.ModelCapabilityQuery;
import com.kinlin.ai.projection.resource.dto.RunResourceUsageQuery;
import com.kinlin.ai.projection.resource.dto.UsageSummaryQuery;

import static com.kinlin.ai.projection.common.mapper.QueryWire.bool;
import static com.kinlin.ai.projection.common.mapper.QueryWire.decimal;
import static com.kinlin.ai.projection.common.mapper.QueryWire.integer;
import static com.kinlin.ai.projection.common.mapper.QueryWire.invalid;
import static com.kinlin.ai.projection.common.mapper.QueryWire.object;
import static com.kinlin.ai.projection.common.mapper.QueryWire.requiredText;
import static com.kinlin.ai.projection.common.mapper.QueryWire.text;

/**
 * Pure whitelist mapping from the agentos_v2.py resource-usage wire to the typed resource
 * DTOs. No I/O, no state, no upstream mutation, no recomputation: usage totals, pressure
 * values, ratios and pagination all stay as the upstream computed them.
 *
 * <p>Required nested objects (usage/contextPressure/composition) must be present and
 * correctly typed — a missing or wrong-typed structure fails the contract loudly instead of
 * passing as empty data, because the frontend readers dereference them unguarded. Nullable
 * values are the honest "not observed" states; ratios only survive as finite doubles.
 */
public final class ResourceUsageProjectionMapper {
    private ResourceUsageProjectionMapper() { }

    public static RunResourceUsageQuery usage(Map<String, Object> wire) {
        return new RunResourceUsageQuery(
                requiredText(wire, "runId"),
                wire.get("capability") == null ? null : capability(object(wire.get("capability"))),
                text(wire, "capabilitySource"), text(wire, "outputPolicy"),
                usageSummary(object(wire.get("usage"))),
                contextPressure(object(wire.get("contextPressure"))),
                composition(object(wire.get("composition"))));
    }

    private static ModelCapabilityQuery capability(Map<?, ?> raw) {
        return new ModelCapabilityQuery(text(raw, "provider"), text(raw, "model"),
                text(raw, "version"), text(raw, "revision"), text(raw, "source"),
                integer(raw, "contextWindowTokens"), integer(raw, "maxOutputTokens"));
    }

    private static UsageSummaryQuery usageSummary(Map<?, ?> raw) {
        return new UsageSummaryQuery(nonNegativeLong(raw, "inputTokens"), nonNegativeLong(raw, "outputTokens"),
                nonNegativeLong(raw, "cacheReadTokens"), nonNegativeLong(raw, "cacheWriteTokens"),
                nonNegativeLong(raw, "reasoningTokens"), nonNegativeLong(raw, "totalTokens"),
                nonNegativeInt(raw, "callCount"), nonNegativeInt(raw, "retryCount"),
                nonNegativeLong(raw, "latencyMs"), decimal(raw, "cacheHitRatio"));
    }

    private static ContextPressureQuery contextPressure(Map<?, ?> raw) {
        return new ContextPressureQuery(decimal(raw, "current"), decimal(raw, "peak"),
                optionalNonNegativeLong(raw, "currentInputTokens"), optionalNonNegativeLong(raw, "peakInputTokens"),
                optionalNonNegativeLong(raw, "contextWindowTokens"), requiredText(raw, "source"));
    }

    private static CompositionQuery composition(Map<?, ?> raw) {
        return new CompositionQuery(nonNegativeInt(raw, "materialManifestCount"),
                nonNegativeInt(raw, "materialFragmentCount"), nonNegativeInt(raw, "taskCount"),
                nonNegativeInt(raw, "completedTaskCount"), nonNegativeInt(raw, "persistedResultFragmentCount"),
                nonNegativeInt(raw, "reducerManifestCount"), nonNegativeInt(raw, "chapterCount"),
                nonNegativeInt(raw, "artifactCount"), requiredBool(raw, "assemblyComplete"),
                decimal(raw, "taskProgress"));
    }

    private static boolean requiredBool(Map<?, ?> source, String field) {
        Boolean value = bool(source, field);
        if (value == null) { throw invalid(); }
        return value;
    }

    private static int nonNegativeInt(Map<?, ?> source, String field) {
        if (!(source.get(field) instanceof Number value)) { throw invalid(); }
        int result = new BigDecimal(value.toString()).intValueExact();
        if (result < 0) { throw invalid(); }
        return result;
    }

    private static long nonNegativeLong(Map<?, ?> source, String field) {
        if (!(source.get(field) instanceof Number value)) { throw invalid(); }
        // Float/Double first build an exact BigDecimal from the binary64 value (no
        // decimal-string detour), then convert exactly — no truncation, no re-rounding.
        BigDecimal exact = value instanceof Float || value instanceof Double
                ? new BigDecimal(value.doubleValue()) : new BigDecimal(value.toString());
        long result = exact.longValueExact();
        if (result < 0) { throw invalid(); }
        return result;
    }

    private static Long optionalNonNegativeLong(Map<?, ?> source, String field) {
        return source.get(field) == null ? null : nonNegativeLong(source, field);
    }
}
