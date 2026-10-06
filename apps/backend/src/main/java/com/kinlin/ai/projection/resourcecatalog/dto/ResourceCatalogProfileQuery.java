package com.kinlin.ai.projection.resourcecatalog.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

import java.math.BigDecimal;
import java.util.List;

/**
 * The static resource identity fields the catalog consumers read
 * (ResourceOverviewPanel / ResourceDetailPanel / ResourceSidebarView). The
 * execution endpoint and its credential reference are dropped by the task book
 * (the catalog answers without endpoints or credentials — the detail drawer's
 * endpoint row is removed with this change); open {@code metadata} maps and the
 * unread upstream health block never enter the response. The labels and cost
 * maps keep their readers as typed key-value rows.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ResourceCatalogProfileQuery(
        String resourceId,
        String resourceType,
        String deploymentTier,
        List<String> capabilities,
        List<String> domains,
        Long version,
        Boolean enabled,
        Long capacity,
        String privacyLevel,
        String dataZone,
        String location,
        String ownerScope,
        List<String> modelIds,
        List<ResourceLabelQuery> labels,
        List<ResourceCostQuery> costMetadata,
        ResourceComputeCapacityQuery computeCapacity,
        String runtimeKind,
        String displayName,
        String nodeId,
        String trust,
        String hostRuntimeId,
        String provider,
        String model,
        Long contextWindowTokens,
        Long maxOutputTokens
) implements QueryResponse {

    /** One stable filter label; dynamic keys are data rows, never a Map field. */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record ResourceLabelQuery(
            String key,
            String value
    ) implements QueryResponse {
    }

    /** One cost metadata scalar; dynamic keys are data rows, never a Map field. */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record ResourceCostQuery(
            String key,
            BigDecimal value
    ) implements QueryResponse {
    }
}
