package com.kinlin.ai.projection.resource;

import java.util.LinkedHashMap;
import java.util.Map;

import com.kinlin.ai.projection.resource.dto.RunResourceUsageQuery;
import com.kinlin.ai.projection.resource.mapper.ResourceUsageProjectionMapper;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;

/**
 * Mapper semantics for the resource-usage overview: required structures must exist (a missing
 * or mistyped object fails the contract instead of passing as empty data), ratios must be
 * finite, counters exact, and nullable "not observed" states preserved.
 */
class ResourceUsageProjectionMapperTest {

    private static Map<String, Object> wireWithout(String key) {
        Map<String, Object> wire = ResourceUsageQueryFixture.observedUsage();
        wire.remove(key);
        return wire;
    }

    private static Map<String, Object> wireWith(String key, Object value) {
        Map<String, Object> wire = ResourceUsageQueryFixture.observedUsage();
        wire.put(key, value);
        return wire;
    }

    @Test
    void requiredStructuresFailLoudlyInsteadOfPassingAsEmptyData() {
        for (String key : new String[] {"usage", "contextPressure", "composition"}) {
            assertThrows(IllegalArgumentException.class, () -> ResourceUsageProjectionMapper.usage(wireWithout(key)), key);
            assertThrows(IllegalArgumentException.class, () -> ResourceUsageProjectionMapper.usage(wireWith(key, null)), key);
            assertThrows(IllegalArgumentException.class, () -> ResourceUsageProjectionMapper.usage(wireWith(key, "not-a-map")), key);
        }
    }

    @Test
    void wrongLeafTypesAndNegativeCountsFailTheContract() {
        assertThrows(IllegalArgumentException.class, () -> ResourceUsageProjectionMapper.usage(wireWith("runId", " ")));
        assertLeafInvalid("usage", "callCount", "2");
        assertLeafInvalid("usage", "retryCount", -1);
        assertLeafInvalid("composition", "assemblyComplete", null);
        assertLeafInvalid("contextPressure", "source", null);
    }

    private static void assertLeafInvalid(String section, String field, Object value) {
        assertLeafThrows(section, field, value, IllegalArgumentException.class);
    }

    private static void assertLeafThrows(String section, String field, Object value,
            Class<? extends Exception> expected) {
        Map<String, Object> wire = ResourceUsageQueryFixture.observedUsage();
        @SuppressWarnings("unchecked")
        Map<String, Object> sectionMap = new LinkedHashMap<>((Map<String, Object>) wire.get(section));
        sectionMap.put(field, value);
        wire.put(section, sectionMap);
        assertThrows(expected, () -> ResourceUsageProjectionMapper.usage(wire),
                section + "." + field);
    }

    @Test
    void ratiosAcceptOnlyFiniteValues() {
        assertLeafInvalid("usage", "cacheHitRatio", Double.POSITIVE_INFINITY);
        assertLeafInvalid("contextPressure", "current", Double.NaN);
        assertLeafInvalid("contextPressure", "peak", Double.NEGATIVE_INFINITY);
    }

    @Test
    void brokenOptionalCountersFailTheContractInsteadOfFabricatingValues() {
        assertLeafInvalid("capability", "contextWindowTokens", "200000");
        assertLeafInvalid("contextPressure", "currentInputTokens", Double.NaN);
        // Fractional counters refuse exact conversion (no silent rounding): the controller
        // maps ArithmeticException to the same 502 contract-invalid envelope.
        assertLeafThrows("usage", "totalTokens", 1.5, ArithmeticException.class);
        assertLeafThrows("capability", "maxOutputTokens", 98304.5, ArithmeticException.class);
    }

    @Test
    void missingCapabilityStaysANullableComponent() {
        RunResourceUsageQuery usage = ResourceUsageProjectionMapper.usage(wireWithout("capability"));
        assertNull(usage.capability());
        assertEquals("observed", usage.capabilitySource());
    }
}
