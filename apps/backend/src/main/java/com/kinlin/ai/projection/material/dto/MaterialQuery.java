package com.kinlin.ai.projection.material.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/** Public manifest facts; ownership metadata remains on the control side. */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record MaterialQuery(String manifestId, String kind, String mediaType, String checksum,
        Long byteLength, Long fragmentCount, Long estimatedTokens, String chunkingVersion,
        Boolean sealed, String createdAt) implements QueryResponse { }
