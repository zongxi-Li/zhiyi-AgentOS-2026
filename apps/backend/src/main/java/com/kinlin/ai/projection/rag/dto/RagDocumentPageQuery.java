package com.kinlin.ai.projection.rag.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

import java.util.List;

/**
 * Typed GET /rag/documents response: the document list fields the frontend reads
 * (doc_id/filename/upload_time/role_id) plus the count. The unread upstream
 * metadata bag is dropped and registered.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record RagDocumentPageQuery(
        List<RagDocumentQuery> documents,
        Long count
) implements QueryResponse {

    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record RagDocumentQuery(
            String doc_id,
            String filename,
            String upload_time,
            String role_id
    ) implements QueryResponse {
    }
}
