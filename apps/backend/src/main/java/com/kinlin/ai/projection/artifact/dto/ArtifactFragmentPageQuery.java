package com.kinlin.ai.projection.artifact.dto;

import com.kinlin.ai.projection.common.dto.QueryResponse;

import java.util.List;

/**
 * 产物分片页查询投影。信封键保持 {manifest, items, nextCursor}；manifest 为与详情
 * 同形的合并投影，nextCursor 为上游 opaque 翻页游标（可为 null，语义原样保留）。
 */
public record ArtifactFragmentPageQuery(
        ArtifactDetailQuery manifest,
        List<ArtifactFragmentQuery> items,
        String nextCursor
) implements QueryResponse { }
