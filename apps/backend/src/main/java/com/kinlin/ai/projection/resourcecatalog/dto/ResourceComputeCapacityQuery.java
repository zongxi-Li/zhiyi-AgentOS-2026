package com.kinlin.ai.projection.resourcecatalog.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/**
 * The compute capacity summary the overview panel renders; not a monitoring metric.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ResourceComputeCapacityQuery(
        Double cpuCores,
        Long memoryMb,
        String gpuType,
        Long gpuMemoryMb,
        Double bandwidthMbps
) implements QueryResponse {
}
