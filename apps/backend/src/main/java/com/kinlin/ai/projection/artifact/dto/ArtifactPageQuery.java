package com.kinlin.ai.projection.artifact.dto;

import com.kinlin.ai.projection.common.dto.QueryResponse;

import java.util.List;

/**
 * Run 产物列表查询投影。信封键保持 {runId, items, total}；identity 命中时 items
 * 为与详情同形的合并投影行，fallback 为 manifest-only 行（artifact/binding 侧 null）。
 */
public record ArtifactPageQuery(
        String runId,
        List<ArtifactDetailQuery> items,
        long total
) implements QueryResponse { }
