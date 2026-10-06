package com.kinlin.ai.projection.resourcecatalog.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;
import java.util.List;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record NodeCatalogQuery(List<NodeItem> items, Long total) implements QueryResponse {
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record NodeItem(NodeProfile profile, String healthStatus, Long snapshotVersion) implements QueryResponse {}
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record NodeProfile(String nodeId, String displayName, String placement,
            String trust, String ownerScope, Boolean enabled, ResourceComputeCapacityQuery computeCapacity)
            implements QueryResponse {}
}
