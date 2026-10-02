package com.kinlin.ai.projection.resource;

import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.projection.resource.mapper.ResourceUsageProjectionMapper;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * JSON contract closure for the resource-usage overview: exact key sets, the dropped
 * scheduler/capability subkeys, NON_NULL absence for unobserved values, SECRET sentinels
 * unreachable, and exact large counter serialization.
 */
class ResourceUsageProjectionSerializationTest {
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private static JsonNode json(Map<String, Object> wire) throws Exception {
        return MAPPER.readTree(MAPPER.writeValueAsString(ResourceUsageProjectionMapper.usage(wire)));
    }

    private static Set<String> keys(JsonNode node) {
        Set<String> names = new LinkedHashSet<>();
        node.fieldNames().forEachRemaining(names::add);
        return names;
    }

    @Test
    void observedEnvelopeHasExactlySevenTopLevelKeysAndDropsTheScheduler() throws Exception {
        JsonNode envelope = json(ResourceUsageQueryFixture.observedUsage());
        assertEquals(Set.of("runId", "capability", "capabilitySource", "outputPolicy",
                "usage", "contextPressure", "composition"), keys(envelope));
        assertEquals("run_1", envelope.path("runId").asText());
        assertEquals("observed", envelope.path("capabilitySource").asText());
    }

    @Test
    void nestedStructuresKeepTheirExactWhitelists() throws Exception {
        JsonNode envelope = json(ResourceUsageQueryFixture.observedUsage());
        assertEquals(Set.of("provider", "model", "version", "revision", "source",
                "contextWindowTokens", "maxOutputTokens"), keys(envelope.path("capability")));
        assertEquals(Set.of("inputTokens", "outputTokens", "cacheReadTokens", "cacheWriteTokens",
                "reasoningTokens", "totalTokens", "callCount", "retryCount", "latencyMs",
                "cacheHitRatio"), keys(envelope.path("usage")));
        assertEquals(Set.of("current", "peak", "currentInputTokens", "peakInputTokens",
                "contextWindowTokens", "source"), keys(envelope.path("contextPressure")));
        assertEquals(Set.of("materialManifestCount", "materialFragmentCount", "taskCount",
                "completedTaskCount", "persistedResultFragmentCount", "reducerManifestCount",
                "chapterCount", "artifactCount", "assemblyComplete", "taskProgress"),
                keys(envelope.path("composition")));
    }

    @Test
    void observedValuesPassThroughWithoutRecomputation() throws Exception {
        JsonNode envelope = json(ResourceUsageQueryFixture.observedUsage());
        assertEquals(12300, envelope.path("usage").path("inputTokens").asLong());
        assertEquals(0.252, envelope.path("usage").path("cacheHitRatio").asDouble());
        assertEquals(5120, envelope.path("usage").path("latencyMs").asLong());
        assertEquals(0.75, envelope.path("contextPressure").path("peak").asDouble());
        assertEquals(0.6, envelope.path("composition").path("taskProgress").asDouble());
        assertEquals("zhipu", envelope.path("capability").path("provider").asText());
    }

    @Test
    void zeroCallPathKeepsRequiredStructuresAndOmitsUnobservedValues() throws Exception {
        JsonNode envelope = json(ResourceUsageQueryFixture.declaredZeroCallUsage());
        assertEquals("declared", envelope.path("capabilitySource").asText());
        assertEquals("catalog_default", envelope.path("outputPolicy").asText());
        // The declared hint only guarantees provider OR model; model stays absent.
        assertEquals("zhipu", envelope.path("capability").path("provider").asText());
        assertFalse(envelope.path("capability").has("model"));
        // Required usage keeps its zero keys; unobserved optional values are absent, not fake.
        assertEquals(0, envelope.path("usage").path("inputTokens").asInt());
        assertEquals(0, envelope.path("usage").path("callCount").asInt());
        assertFalse(envelope.path("usage").has("cacheHitRatio"));
        assertFalse(envelope.path("contextPressure").has("current"));
        assertFalse(envelope.path("contextPressure").has("peak"));
        assertEquals(131072, envelope.path("contextPressure").path("contextWindowTokens").asLong());
        assertEquals("capability_declared", envelope.path("contextPressure").path("source").asText());
        assertFalse(envelope.path("composition").has("taskProgress"));
        assertFalse(envelope.path("composition").path("assemblyComplete").asBoolean());
    }

    @Test
    void secretSentinelsNeverReachTheSerializedResponse() throws Exception {
        String observed = MAPPER.writeValueAsString(
                ResourceUsageProjectionMapper.usage(ResourceUsageQueryFixture.observedUsage()));
        assertFalse(observed.contains(ResourceUsageQueryFixture.SECRET));
        String declared = MAPPER.writeValueAsString(
                ResourceUsageProjectionMapper.usage(ResourceUsageQueryFixture.declaredZeroCallUsage()));
        assertFalse(declared.contains(ResourceUsageQueryFixture.SECRET));
    }

    @Test
    void largeTokenCountsStayExactThroughSerialization() throws Exception {
        Map<String, Object> wire = ResourceUsageQueryFixture.observedUsage();
        @SuppressWarnings("unchecked")
        Map<String, Object> usage = (Map<String, Object>) wire.get("usage");
        usage.put("inputTokens", 3_000_000_000L); // beyond the int range, inside a real long
        JsonNode envelope = json(wire);
        JsonNode inputTokens = envelope.path("usage").path("inputTokens");
        assertTrue(inputTokens.isLong(), "a 3e9 token sum must serialize as a long, not truncate");
        assertEquals(3_000_000_000L, inputTokens.asLong());
    }

    @Test
    void callPageEnvelopeKeepsItsExactWhitelistAndDropsRowCapability() throws Exception {
        JsonNode page = MAPPER.readTree(MAPPER.writeValueAsString(
                ResourceUsageProjectionMapper.callPage(ResourceUsageQueryFixture.firstCallPage())));
        assertEquals(Set.of("runId", "items", "nextCursor", "total"), keys(page));
        assertEquals("run_1", page.path("runId").asText());
        assertEquals("2", page.path("nextCursor").asText());
        assertEquals(25, page.path("total").asInt());
        assertEquals(2, page.path("items").size());
        JsonNode row = page.path("items").get(0);
        assertEquals(Set.of("callId", "stepId", "provider", "model", "createdAt", "latencyMs",
                "usage", "finishReason", "outputPolicy", "requestedOutputTokens",
                "effectiveOutputTokens", "effectiveReason", "outputExhausted", "partIndex",
                "callChainId", "contextPressure"), keys(row));
        assertEquals(Set.of("inputTokens", "outputTokens", "cacheReadTokens", "cacheWriteTokens",
                "reasoningTokens", "totalTokens"), keys(row.path("usage")));
    }

    @Test
    void exhaustedCallRowKeepsRequiredValuesAndOmitsUnobservedOnes() throws Exception {
        JsonNode page = MAPPER.readTree(MAPPER.writeValueAsString(
                ResourceUsageProjectionMapper.callPage(ResourceUsageQueryFixture.firstCallPage())));
        JsonNode exhausted = page.path("items").get(1);
        assertTrue(exhausted.path("outputExhausted").asBoolean());
        assertEquals(0, exhausted.path("usage").path("inputTokens").asInt());
        assertEquals("provider_required", exhausted.path("outputPolicy").asText());
        for (String absent : new String[] {"stepId", "provider", "model", "finishReason",
                "requestedOutputTokens", "effectiveOutputTokens", "effectiveReason", "partIndex",
                "callChainId", "contextPressure", "capability"}) {
            assertTrue(!exhausted.has(absent), absent + " must be absent, not null");
        }
    }

    @Test
    void lastAndEmptyCallPagesKeepUpstreamSemantics() throws Exception {
        JsonNode last = MAPPER.readTree(MAPPER.writeValueAsString(
                ResourceUsageProjectionMapper.callPage(ResourceUsageQueryFixture.lastCallPage())));
        assertTrue(!last.has("nextCursor"), "the final page has no cursor");
        assertEquals(25, last.path("total").asInt());
        assertEquals(1, last.path("items").size());

        JsonNode empty = MAPPER.readTree(MAPPER.writeValueAsString(
                ResourceUsageProjectionMapper.callPage(ResourceUsageQueryFixture.emptyCallPage())));
        assertTrue(!empty.has("nextCursor"));
        assertEquals(0, empty.path("total").asInt());
        assertEquals(0, empty.path("items").size());
    }

    @Test
    void callRowSecretsNeverReachTheSerializedResponse() throws Exception {
        String body = MAPPER.writeValueAsString(
                ResourceUsageProjectionMapper.callPage(ResourceUsageQueryFixture.firstCallPage()));
        assertFalse(body.contains(ResourceUsageQueryFixture.SECRET));
    }
}
