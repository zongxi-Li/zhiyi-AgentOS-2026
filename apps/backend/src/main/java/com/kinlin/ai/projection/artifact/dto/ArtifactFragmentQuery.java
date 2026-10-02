package com.kinlin.ai.projection.artifact.dto;

import java.util.List;

/**
 * 产物分片行公共投影：ContentFragmentRef 全部公开字段 + content 正文。
 * sourceRefs/constraintRefs 为公共来源引用（步骤/约束的 opaque id 列表），
 * 非存储路径或绑定信息；cursor 定位与 sequence 顺序契约逐字保留。
 */
public record ArtifactFragmentQuery(
        String fragmentId,
        String manifestId,
        int sequence,
        String checksum,
        long byteLength,
        Long estimatedTokens,
        List<String> sourceRefs,
        List<String> constraintRefs,
        String verificationStatus,
        boolean complete,
        String content
) { }
