package com.kinlin.ai.projection.resourcecatalog.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

import java.util.List;

/**
 * Typed GET /resources response over the agentos_v2.py {@code get_resources} wire.
 * Field set follows the verified readers (ResourceOverviewPanel, ResourceSidebarView);
 * the upstream executionEndpoint/authReference, credential-adjacent fields, open
 * metadata maps and the unread health block are dropped and registered — the
 * resource catalog answers without endpoints or credentials.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ResourceCatalogQuery(
        List<ResourceCatalogItemQuery> items,
        Long total
) implements QueryResponse {
}
