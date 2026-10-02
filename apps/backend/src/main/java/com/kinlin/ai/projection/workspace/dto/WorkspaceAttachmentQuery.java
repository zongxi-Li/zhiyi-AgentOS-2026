package com.kinlin.ai.projection.workspace.dto;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * Mission input attachment inside the Workspace envelope, whitelisted to the TS
 * InputAttachment shape the workspace already exposes (ownerUserId/ownerTenantId/
 * storageKey are excluded upstream; the open {@code metadata} container is dropped here —
 * MissionEditor reads only originalFilename/status/sizeBytes/attachmentId). The TS-declared
 * {@code errorCode} does not exist in the Python model (declaration drift) and is not
 * projected.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record WorkspaceAttachmentQuery(
        String attachmentId,
        String originalFilename,
        String mimeType,
        String extension,
        long sizeBytes,
        String sha256,
        String status,
        String extractedContentRef,
        long characterCount,
        String parser,
        String parseError,
        String createdAt,
        String updatedAt
) { }
