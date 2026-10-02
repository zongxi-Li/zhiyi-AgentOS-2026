package com.kinlin.ai.projection.artifact.dto;

import com.kinlin.ai.projection.common.dto.QueryResponse;

/**
 * Artifact 详情/列表行的平铺公共投影（保持既有三模型合并的平铺 wire 形状，不嵌套化）。
 * identity 命中时上游按 manifest → artifact → RunArtifactBinding 顺序合并、后者覆盖
 * createdAt/checksum/mediaType 同名键，Mapper 只读取已合并结果、不重新查模型；
 * manifest-only fallback 时 artifact/binding 侧字段为 null。
 * <p>隔离的内部键（不进入公共 wire）：ownerType/ownerId（存储归属）、chunkingVersion
 * （内部分块版本）、bindingId（内部绑定标识）、metadata（开放容器；生产者仅为
 * logicalRole/identityVersion/sourceAttachmentIds 与模型自由键，均无公共消费者，
 * logicalRole 已在 Workspace entry 一等字段中公开）。</p>
 */
public record ArtifactDetailQuery(
        String manifestId,
        String kind,
        String mediaType,
        String checksum,
        long byteLength,
        int fragmentCount,
        Long estimatedTokens,
        boolean sealed,
        String createdAt,
        String artifactId,
        String missionId,
        String originRunId,
        String taskId,
        String semanticTaskKey,
        String artifactKey,
        String acgNodeId,
        String producerAttemptId,
        String name,
        String artifactType,
        String contentRef,
        String runId,
        String disposition,
        String sourceRunId
) implements QueryResponse { }
