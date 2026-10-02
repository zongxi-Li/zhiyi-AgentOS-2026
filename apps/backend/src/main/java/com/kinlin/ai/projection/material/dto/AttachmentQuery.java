package com.kinlin.ai.projection.material.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/** Existing parsing facts and public content references, without storage or arbitrary metadata. */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record AttachmentQuery(String attachmentId, String originalFilename, String filename,
        String mimeType, String extension, Long sizeBytes, String sha256, String status,
        String extractedContentRef, Long characterCount, String parser, String parseError,
        String errorCode, String createdAt, String updatedAt) implements QueryResponse { }
