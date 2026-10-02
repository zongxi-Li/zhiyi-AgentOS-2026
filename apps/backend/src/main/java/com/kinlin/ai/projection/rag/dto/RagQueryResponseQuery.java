package com.kinlin.ai.projection.rag.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.kinlin.ai.projection.common.dto.QueryResponse;

import java.util.List;

/**
 * Typed read-only RAG query response over the RagService wire, replacing the
 * client record's raw {@code List<Map<String,Object>>} sources with typed rows
 * shaped by the verified frontend reader (rag.ts RagResponse.sources).
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record RagQueryResponseQuery(
        String answer,
        List<RagSourceQuery> sources,
        Double confidence
) implements QueryResponse {

    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record RagSourceQuery(
            String title,
            String url,
            String content
    ) implements QueryResponse {
    }
}
