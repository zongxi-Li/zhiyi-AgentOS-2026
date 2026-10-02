package com.kinlin.ai.projection.resource;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.kinlin.ai.projection.resource.dto.ResourceCallPageQuery;
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
    @SuppressWarnings("unchecked")
    void optionalQuotasKeepDecodedIntegersWithoutDecimalStringRounding() {
        double boundary = Math.nextDown(0x1p63);
        long expected = 9223372036854774784L;
        Map<String, Object> wire = ResourceUsageQueryFixture.observedUsage();
        Map<String, Object> capability = new LinkedHashMap<>((Map<String, Object>) wire.get("capability"));
        capability.put("contextWindowTokens", boundary);
        capability.put("maxOutputTokens", boundary);
        wire.put("capability", capability);
        var projected = ResourceUsageProjectionMapper.usage(wire).capability();
        assertEquals(expected, projected.contextWindowTokens());
        assertEquals(expected, projected.maxOutputTokens());

        Map<String, Object> page = ResourceUsageQueryFixture.firstCallPage();
        Map<String, Object> row = new LinkedHashMap<>((Map<String, Object>) ((List<?>) page.get("items")).get(0));
        row.put("requestedOutputTokens", boundary);
        row.put("effectiveOutputTokens", boundary);
        page.put("items", List.of(row));
        var call = ResourceUsageProjectionMapper.callPage(page).items().get(0);
        assertEquals(expected, call.requestedOutputTokens());
        assertEquals(expected, call.effectiveOutputTokens());
        assertCallRowThrows(page, "requestedOutputTokens", 0x1p63, ArithmeticException.class);
        assertCallRowThrows(page, "effectiveOutputTokens", 1.5, ArithmeticException.class);
    }

    @Test
    void missingCapabilityStaysANullableComponent() {
        RunResourceUsageQuery usage = ResourceUsageProjectionMapper.usage(wireWithout("capability"));
        assertNull(usage.capability());
        assertEquals("observed", usage.capabilitySource());
    }

    @Test
    void callsPageKeepsFilterAndPaginationSemantics() {
        ResourceCallPageQuery page =
                ResourceUsageProjectionMapper.callPage(ResourceUsageQueryFixture.firstCallPage());
        assertEquals("run_1", page.runId());
        assertEquals(2, page.items().size());
        // The cursor passes through verbatim; the mapper never parses or rewrites it.
        assertEquals("2", page.nextCursor());
        assertEquals(25, page.total());
        var row = page.items().get(0);
        assertEquals("trace_001", row.callId());
        assertEquals(1234, row.latencyMs());
        assertEquals(12200, row.usage().totalTokens());
        assertEquals(0.5, row.contextPressure());
    }

    @Test
    void missingCallsListFailsLoudlyInsteadOfPassingAsAnEmptyPage() {
        Map<String, Object> missing = ResourceUsageQueryFixture.firstCallPage();
        missing.remove("items");
        assertThrows(IllegalArgumentException.class, () -> ResourceUsageProjectionMapper.callPage(missing));
        Map<String, Object> nulled = ResourceUsageQueryFixture.firstCallPage();
        nulled.put("items", null);
        assertThrows(IllegalArgumentException.class, () -> ResourceUsageProjectionMapper.callPage(nulled));
        Map<String, Object> mistyped = ResourceUsageQueryFixture.firstCallPage();
        mistyped.put("items", "not-a-list");
        assertThrows(IllegalArgumentException.class, () -> ResourceUsageProjectionMapper.callPage(mistyped));
    }

    @Test
    void brokenCallRowsFailTheContractInsteadOfFabricatingValues() {
        assertCallRowInvalid(ResourceUsageQueryFixture.firstCallPage(), "callId", null);
        assertCallRowInvalid(ResourceUsageQueryFixture.firstCallPage(), "outputPolicy", "");
        assertCallRowInvalid(ResourceUsageQueryFixture.firstCallPage(), "outputExhausted", null);
        assertCallRowInvalid(ResourceUsageQueryFixture.firstCallPage(), "latencyMs", -1);
        assertCallRowInvalid(ResourceUsageQueryFixture.firstCallPage(), "usage", null);
        assertCallRowInvalid(ResourceUsageQueryFixture.firstCallPage(), "partIndex", "1");
        assertCallRowInvalid(ResourceUsageQueryFixture.firstCallPage(), "contextPressure", Double.NaN);
        assertCallRowThrows(ResourceUsageQueryFixture.firstCallPage(), "requestedOutputTokens", 98304.5,
                ArithmeticException.class);
    }

    private static void assertCallRowInvalid(Map<String, Object> page, String field, Object value) {
        assertCallRowThrows(page, field, value, IllegalArgumentException.class);
    }

    @SuppressWarnings("unchecked")
    private static void assertCallRowThrows(Map<String, Object> page, String field, Object value,
            Class<? extends Exception> expected) {
        Map<String, Object> row = new LinkedHashMap<>((Map<String, Object>) ((List<?>) page.get("items")).get(0));
        row.put(field, value);
        Map<String, Object> edited = new LinkedHashMap<>(page);
        edited.put("items", List.of(row));
        assertThrows(expected, () -> ResourceUsageProjectionMapper.callPage(edited), field);
    }
}
