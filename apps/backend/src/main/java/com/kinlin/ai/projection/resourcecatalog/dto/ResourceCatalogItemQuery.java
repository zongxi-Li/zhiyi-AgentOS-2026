package com.kinlin.ai.projection.resourcecatalog.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

import java.util.List;

/**
 * One catalog row: the static profile fields with readers, the last observed
 * availability snapshot and the snapshot version the detail drawer renders.
 * Snapshot identity duplicates the profile resourceId and the observation
 * sequence has no reader, so both stay out.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ResourceCatalogItemQuery(
        ResourceCatalogProfileQuery profile,
        ResourceCatalogSnapshotQuery snapshot,
        Long snapshotVersion
) implements QueryResponse {
}
