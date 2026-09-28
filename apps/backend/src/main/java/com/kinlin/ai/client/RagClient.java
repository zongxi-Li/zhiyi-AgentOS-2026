package com.kinlin.ai.client;

import org.springframework.core.io.Resource;

import java.util.List;
import java.util.Map;

/**
 * What the Java platform needs from the Python RAG capability
 * ({@code /rag/**} family): retrieval, document upload/list/delete.
 *
 * <p>Results are the client-level projection of the upstream contract; transport
 * failures surface as {@link PlatformAiClientException}. Fallback decisions stay
 * with application services.</p>
 */
public interface RagClient {

    RagQueryResult query(RagQueryCommand command);

    /** Uploads a document part and returns the upstream document id. */
    String uploadDocument(DocumentUpload upload);

    /** Document listing projection; shape stays dynamic (N1.2 owns query projections). */
    Map<String, Object> listDocuments(String roleId);

    void deleteDocument(String docId);

    record RagQueryResult(
            String answer,
            List<Map<String, Object>> sources,
            Double confidence
    ) {
    }

    record RagQueryCommand(
            String query,
            Integer topK,
            String contextId,
            String roleId,
            Boolean useKnowledgeGraph
    ) {
    }

    /**
     * A document part to upload. {@code content} is streamed (never fully buffered);
     * {@code contentType} falls back to {@code application/octet-stream} when null.
     */
    record DocumentUpload(
            Resource content,
            String filename,
            String contentType,
            String roleId
    ) {
    }
}
