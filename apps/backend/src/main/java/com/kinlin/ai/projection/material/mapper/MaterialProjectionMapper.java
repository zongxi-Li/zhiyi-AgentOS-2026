package com.kinlin.ai.projection.material.mapper;

import com.kinlin.ai.projection.material.dto.AttachmentQuery;
import com.kinlin.ai.projection.material.dto.MaterialQuery;
import java.util.Map;
import static com.kinlin.ai.projection.common.mapper.QueryWire.*;

/** Pure output mapping of the existing gateway response; no material loading or parsing. */
public final class MaterialProjectionMapper {
    private MaterialProjectionMapper() { }

    public static MaterialQuery material(Map<String, Object> wire) {
        return new MaterialQuery(requiredText(wire, "manifestId"), text(wire, "kind"),
                text(wire, "mediaType"), text(wire, "checksum"), integer(wire, "byteLength"),
                integer(wire, "fragmentCount"), integer(wire, "estimatedTokens"),
                text(wire, "chunkingVersion"), bool(wire, "sealed"), text(wire, "createdAt"));
    }

    public static AttachmentQuery attachment(Map<String, Object> wire) {
        return new AttachmentQuery(requiredText(wire, "attachmentId"), text(wire, "originalFilename"),
                text(wire, "filename"), text(wire, "mimeType"), text(wire, "extension"),
                integer(wire, "sizeBytes"), text(wire, "sha256"), text(wire, "status"),
                text(wire, "extractedContentRef"), integer(wire, "characterCount"), text(wire, "parser"),
                text(wire, "parseError"), text(wire, "errorCode"), text(wire, "createdAt"), text(wire, "updatedAt"));
    }
}
