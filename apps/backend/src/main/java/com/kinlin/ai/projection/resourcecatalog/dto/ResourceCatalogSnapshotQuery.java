package com.kinlin.ai.projection.resourcecatalog.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/**
 * The last observed availability fields the catalog consumers read, plus the
 * observation timestamp the detail drawer renders. The upstream health block and
 * open metrics map have no reader and are dropped.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ResourceCatalogSnapshotQuery(
        String healthStatus,
        Double utilization,
        Double latencyMs,
        Long availableSlots,
        Double reliability,
        String observedAt
) implements QueryResponse {
}
