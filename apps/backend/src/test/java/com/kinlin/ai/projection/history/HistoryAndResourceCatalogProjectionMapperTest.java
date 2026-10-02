package com.kinlin.ai.projection.history;

import java.math.BigDecimal;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.projection.history.mapper.HistoryConfigProjectionMapper;
import com.kinlin.ai.projection.resourcecatalog.mapper.ResourceCatalogProjectionMapper;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Wire contracts for the reopen configuration and the resource catalog: reader
 * field sets only, flat-scalar plugin data rows, and a catalog without endpoints,
 * credential references or open metadata maps.
 */
class HistoryAndResourceCatalogProjectionMapperTest {
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final String SECRET = "SECRET-HISTORY-12345";

    private static Map<String, Object> row(Object... keyValues) {
        Map<String, Object> result = new java.util.LinkedHashMap<>();
        for (int index = 0; index < keyValues.length; index += 2) {
            result.put((String) keyValues[index], keyValues[index + 1]);
        }
        return result;
    }

    private static Set<String> keys(JsonNode node) {
        Set<String> names = new LinkedHashSet<>();
        node.fieldNames().forEachRemaining(names::add);
        return names;
    }

    private static JsonNode json(Object mapped) throws Exception {
        return MAPPER.readTree(MAPPER.writeValueAsString(mapped));
    }

    @Test
    void historyConfigKeepsTheVerifiedReopenFieldsOnly() throws Exception {
        JsonNode body = json(HistoryConfigProjectionMapper.historyConfig(row(
                "runId", "run_1", "title", "合同审查", "reviewMode", "human_in_loop",
                "enabledPluginIds", List.of("kinlin.legal"),
                "input", row(
                        "taskGoal", "审查合同", "userIntent", "识别风险",
                        "materialText", "正文", "materialIds", List.of("mat_1"),
                        "constraints", List.of("两周内"), "expectedArtifacts", List.of("报告"),
                        "planningMode", "template_preferred", "planningDiversity", "stable",
                        "capabilityProfile", "full", "thinkingMode", "deep",
                        "reasoningEffort", "high", "planningSeed", 42, "webSearchEnabled", true,
                        "contractText", "合同条款...",
                        "attachmentIds", List.of("att_1"), "inputAttachments", List.of(),
                        "materialRefs", List.of("ref_1"), "contractType", "采购",
                        "legalReviewGoal", "目标", "evidenceFirst", true,
                        "metadata", Map.of("internal", SECRET)))));
        assertEquals(Set.of("runId", "title", "reviewMode", "enabledPluginIds", "input"), keys(body));
        JsonNode input = body.path("input");
        assertEquals(Set.of("taskGoal", "userIntent", "materialText", "contractText", "materialIds",
                "constraints", "expectedArtifacts", "planningMode", "planningDiversity",
                "capabilityProfile", "thinkingMode", "reasoningEffort", "planningSeed",
                "webSearchEnabled"), keys(input));
        String bodyText = MAPPER.writeValueAsString(body);
        assertFalse(bodyText.contains("attachmentIds"));
        assertFalse(bodyText.contains("contractType"), "unread legal top-level keys are dropped");
        assertFalse(bodyText.contains(SECRET));
    }

    @Test
    void pluginDataBecomesFlatScalarAssociationRows() throws Exception {
        JsonNode input = json(HistoryConfigProjectionMapper.historyConfig(row(
                "runId", "run_1",
                "input", row("pluginData", row(
                        "kinlin.legal", row("contractText", "条款", "useTemplateWorkflow", false,
                                "maxRevisions", 2, "nested", Map.of("drop", "me")),
                        "industrial", row("evidenceFirst", true))))))
                .path("input").path("pluginData");
        assertEquals(2, input.size());
        JsonNode legal = input.get(0);
        assertEquals("kinlin.legal", legal.path("pluginId").asText());
        assertEquals(Set.of("pluginId", "entries"), keys(legal));
        assertEquals(3, legal.path("entries").size(), "nested values have no representation and drop");
        JsonNode contractText = legal.path("entries").get(0);
        assertEquals("contractText", contractText.path("name").asText());
        assertEquals("条款", contractText.path("text").asText());
        assertFalse(contractText.has("bool"));
        JsonNode industrial = input.get(1);
        assertTrue(industrial.path("entries").get(0).path("bool").asBoolean());
    }

    @Test
    void damagedHistoryEnvelopeFailsLoudly() {
        assertThrows(IllegalArgumentException.class, () -> HistoryConfigProjectionMapper.historyConfig(row(
                "title", "没有 runId")));
        assertThrows(IllegalArgumentException.class, () -> HistoryConfigProjectionMapper.historyConfig(row(
                "runId", "run_1", "input", "broken")));
    }

    @Test
    void resourceCatalogAnswersWithoutEndpointsCredentialsOrMetadata() throws Exception {
        Map<String, Object> item = row(
                "profile", row("resourceId", "res_1", "resourceType", "agent",
                        "deploymentTier", "local", "capabilities", List.of("report"),
                        "version", 3, "enabled", true, "capacity", 4,
                        "privacyLevel", "internal", "dataZone", "cn-north", "location", "北京",
                        "ownerScope", "tenant-1", "modelIds", List.of("m1"),
                        "labels", Map.of("env", "prod"), "costMetadata", Map.of("usd", 1.5),
                        "computeCapacity", row("cpuCores", 8.0, "memoryMb", 16384,
                                "gpuType", null, "gpuMemoryMb", 0, "bandwidthMbps", 1000.0),
                        "executionEndpoint", row("protocol", "https", "address", "https://internal",
                                "authReference", "vault:key"),
                        "ownerScope", "tenant-1", "privacyLevel", "internal",
                        "metadata", Map.of("internal", SECRET), "labels", Map.of("env", "prod"),
                        "costMetadata", Map.of("usd", 1.5), "modelIds", List.of("m1")),
                "snapshot", row("resourceId", "res_1", "observationSequence", 9,
                        "observedAt", "2026-10-02T10:00:00Z", "availableSlots", 2,
                        "healthStatus", "online", "utilization", 0.25, "latencyMs", 120.5,
                        "reliability", 0.9, "metrics", Map.of("qps", 3.0)),
                "snapshotVersion", 5,
                "health", row("healthy", true, "status", "online", "healthSource", "Mem"));
        JsonNode body = json(ResourceCatalogProjectionMapper.catalog(row(
                "items", List.of(item),
                "total", 1)));
        assertEquals(Set.of("items", "total"), keys(body));
        JsonNode catalogItem = body.path("items").get(0);
        assertEquals(Set.of("profile", "snapshot", "snapshotVersion"), keys(catalogItem));
        assertEquals(Set.of("resourceId", "resourceType", "deploymentTier", "capabilities",
                "domains", "version", "enabled", "capacity", "privacyLevel", "dataZone",
                "location", "ownerScope", "modelIds", "labels", "costMetadata", "computeCapacity"),
                keys(catalogItem.path("profile")));
        assertEquals(Set.of("healthStatus", "utilization", "latencyMs", "availableSlots",
                "reliability", "observedAt"), keys(catalogItem.path("snapshot")));
        assertEquals("env", catalogItem.path("profile").path("labels").get(0).path("key").asText());
        assertEquals("prod", catalogItem.path("profile").path("labels").get(0).path("value").asText());
        assertEquals(0, new BigDecimal("1.5").compareTo(new BigDecimal(
                catalogItem.path("profile").path("costMetadata").get(0).path("value").asText())));
        String bodyText = MAPPER.writeValueAsString(body);
        assertFalse(bodyText.contains("executionEndpoint"));
        assertFalse(bodyText.contains("authReference"));
        assertFalse(bodyText.contains("vault:"));
        assertFalse(bodyText.contains("https://internal"));
        assertFalse(bodyText.contains(SECRET));
        assertFalse(bodyText.contains("healthSource"), "the unread upstream health block is dropped");
        assertFalse(bodyText.contains("qps"), "the unread open metrics map is dropped");
        assertEquals(0.25, catalogItem.path("snapshot").path("utilization").asDouble());
    }

    @Test
    void damagedCatalogEnvelopeFailsLoudly() {
        assertThrows(IllegalArgumentException.class, () -> ResourceCatalogProjectionMapper.catalog(row("total", 0)));
        assertThrows(IllegalArgumentException.class, () -> ResourceCatalogProjectionMapper.catalog(row(
                "items", List.of(row("profile", row("resourceId", "res"))), "total", 1)));
        assertThrows(IllegalArgumentException.class, () -> ResourceCatalogProjectionMapper.catalog(row(
                "items", List.of(row(
                        "profile", row("resourceId", "res", "healthStatus", "x"),
                        "snapshot", row("utilization", 0.5))),
                "total", 1)));
    }
}
