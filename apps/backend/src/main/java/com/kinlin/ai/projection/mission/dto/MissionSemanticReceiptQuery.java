package com.kinlin.ai.projection.mission.dto;

import com.kinlin.ai.projection.common.dto.QueryResponse;

/** The original authorized semantic operation receipt, including conflicts and no-op results. */
public record MissionSemanticReceiptQuery(int fingerprintVersion, String requestFingerprint, String actorId,
                                         String tenantId, MissionSemanticQuery.Result result,
                                         String createdAt) implements QueryResponse { }
