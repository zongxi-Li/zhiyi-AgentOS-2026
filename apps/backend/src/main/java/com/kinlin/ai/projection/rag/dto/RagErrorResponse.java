package com.kinlin.ai.projection.rag.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

/**
 * The 500 error body of the document-list query, keeping the upstream
 * {@code {error}} shape for the frontend client.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record RagErrorResponse(
        String error
) implements QueryResponse {
}
