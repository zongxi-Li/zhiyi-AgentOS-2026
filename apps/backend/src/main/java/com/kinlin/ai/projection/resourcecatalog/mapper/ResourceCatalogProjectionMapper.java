package com.kinlin.ai.projection.resourcecatalog.mapper;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import com.kinlin.ai.projection.common.mapper.QueryWire;
import com.kinlin.ai.projection.resourcecatalog.dto.ResourceCatalogItemQuery;
import com.kinlin.ai.projection.resourcecatalog.dto.ResourceCatalogProfileQuery;
import com.kinlin.ai.projection.resourcecatalog.dto.ResourceCatalogQuery;
import com.kinlin.ai.projection.resourcecatalog.dto.ResourceCatalogSnapshotQuery;
import com.kinlin.ai.projection.resourcecatalog.dto.ResourceComputeCapacityQuery;
import com.kinlin.ai.projection.resourcecatalog.dto.NodeCatalogQuery;

import static com.kinlin.ai.projection.common.mapper.QueryWire.bool;
import static com.kinlin.ai.projection.common.mapper.QueryWire.decimal;
import static com.kinlin.ai.projection.common.mapper.QueryWire.invalid;
import static com.kinlin.ai.projection.common.mapper.QueryWire.integer;
import static com.kinlin.ai.projection.common.mapper.QueryWire.items;
import static com.kinlin.ai.projection.common.mapper.QueryWire.object;
import static com.kinlin.ai.projection.common.mapper.QueryWire.requiredText;
import static com.kinlin.ai.projection.common.mapper.QueryWire.text;
import static com.kinlin.ai.projection.common.mapper.QueryWire.texts;

/**
 * Pure whitelist mapping from the agentos_v2.py {@code get_resources} wire to the
 * typed resource catalog. No I/O, no recomputation: the persisted snapshot health
 * passes through as-is and the catalog never answers with endpoints, credential
 * references or open metadata maps (the task book's "no endpoint/credential"
 * rule; the detail drawer's endpoint row is removed with this change). The labels
 * and cost maps keep their catalog readers as typed key-value rows.
 */
public final class ResourceCatalogProjectionMapper {
    private ResourceCatalogProjectionMapper() {
    }

    public static ResourceCatalogQuery catalog(Map<String, Object> wire) {
        if (wire.get("items") == null) {
            throw invalid();
        }
        return new ResourceCatalogQuery(
                items(wire.get("items"), ResourceCatalogProjectionMapper::item),
                integer(wire, "total"));
    }

    private static ResourceCatalogItemQuery item(Map<?, ?> raw) {
        return new ResourceCatalogItemQuery(
                profile(object(raw.get("profile"))),
                snapshot(object(raw.get("snapshot"))),
                integer(raw, "snapshotVersion"));
    }

    public static NodeCatalogQuery nodes(Map<String, Object> wire) {
        if (wire.get("items") == null) throw invalid();
        return new NodeCatalogQuery(items(wire.get("items"), raw -> {
            Map<?, ?> p = object(raw.get("profile"));
            Map<?, ?> health = object(raw.get("health"));
            return new NodeCatalogQuery.NodeItem(new NodeCatalogQuery.NodeProfile(
                    requiredText(p, "nodeId"), text(p, "displayName"), text(p, "placement"),
                    text(p, "trust"), text(p, "ownerScope"), bool(p, "enabled"),
                    p.get("computeCapacity") == null ? null : computeCapacity(object(p.get("computeCapacity")))),
                    text(health, "status"), integer(raw, "snapshotVersion"));
        }), integer(wire, "total"));
    }

    private static ResourceCatalogProfileQuery profile(Map<?, ?> raw) {
        return new ResourceCatalogProfileQuery(
                requiredText(raw, "resourceId"),
                text(raw, "resourceType"),
                text(raw, "deploymentTier"),
                texts(raw.get("capabilities")),
                texts(raw.get("domains")),
                integer(raw, "version"),
                bool(raw, "enabled"),
                integer(raw, "capacity"),
                text(raw, "privacyLevel"),
                text(raw, "dataZone"),
                text(raw, "location"),
                text(raw, "ownerScope"),
                texts(raw.get("modelIds")),
                labels(raw.get("labels")),
                costMetadata(raw.get("costMetadata")),
                raw.get("computeCapacity") == null
                        ? null : computeCapacity(object(raw.get("computeCapacity"))),
                text(raw, "runtimeKind"), text(raw, "displayName"),
                text(raw, "nodeId"), text(raw, "trust"), text(raw, "hostRuntimeId"),
                text(raw, "provider"), text(raw, "model"),
                integer(raw, "contextWindowTokens"), integer(raw, "maxOutputTokens"));
    }

    /** Dynamic catalog maps keep their readers as typed key-value rows. */
    private static List<ResourceCatalogProfileQuery.ResourceLabelQuery> labels(Object raw) {
        if (!(raw instanceof Map<?, ?> map)) {
            return null;
        }
        List<ResourceCatalogProfileQuery.ResourceLabelQuery> rows = new ArrayList<>();
        for (Map.Entry<?, ?> entry : map.entrySet()) {
            if (entry.getKey() instanceof String key && !key.isBlank()
                    && entry.getValue() instanceof String value) {
                rows.add(new ResourceCatalogProfileQuery.ResourceLabelQuery(key, value));
            }
        }
        return rows.isEmpty() ? null : rows;
    }

    private static List<ResourceCatalogProfileQuery.ResourceCostQuery> costMetadata(Object raw) {
        if (!(raw instanceof Map<?, ?> map)) {
            return null;
        }
        List<ResourceCatalogProfileQuery.ResourceCostQuery> rows = new ArrayList<>();
        for (Map.Entry<?, ?> entry : map.entrySet()) {
            if (entry.getKey() instanceof String key && !key.isBlank()
                    && entry.getValue() instanceof Number number) {
                rows.add(new ResourceCatalogProfileQuery.ResourceCostQuery(key,
                        new BigDecimal(number.toString())));
            }
        }
        return rows.isEmpty() ? null : rows;
    }

    private static ResourceComputeCapacityQuery computeCapacity(Map<?, ?> raw) {
        return new ResourceComputeCapacityQuery(
                decimal(raw, "cpuCores"),
                integer(raw, "memoryMb"),
                text(raw, "gpuType"),
                integer(raw, "gpuMemoryMb"),
                decimal(raw, "bandwidthMbps"));
    }

    private static ResourceCatalogSnapshotQuery snapshot(Map<?, ?> raw) {
        return new ResourceCatalogSnapshotQuery(
                requiredText(raw, "healthStatus"),
                decimal(raw, "utilization"),
                decimal(raw, "latencyMs"),
                integer(raw, "availableSlots"),
                decimal(raw, "reliability"),
                text(raw, "observedAt"));
    }
}
