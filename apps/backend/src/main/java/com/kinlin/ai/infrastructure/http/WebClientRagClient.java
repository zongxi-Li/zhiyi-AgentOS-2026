package com.kinlin.ai.infrastructure.http;

import com.kinlin.ai.client.RagClient;
import org.springframework.http.MediaType;
import org.springframework.http.client.MultipartBodyBuilder;
import org.springframework.stereotype.Component;
import org.springframework.web.util.UriBuilder;

import java.util.HashMap;
import java.util.Map;

/** WebClient implementation of the RAG capability ({@code /rag/**} family). */
@Component
public class WebClientRagClient implements RagClient {

    private final PlatformAiTransport transport;

    public WebClientRagClient(PlatformAiTransport transport) {
        this.transport = transport;
    }

    @Override
    public RagQueryResult query(RagQueryCommand command) {
        Map<String, Object> requestBody = new HashMap<>();
        requestBody.put("query", command.query());
        requestBody.put("top_k", command.topK() != null ? command.topK() : 5);
        if (command.contextId() != null) {
            requestBody.put("context_id", command.contextId());
        }
        if (command.roleId() != null && !command.roleId().isBlank()) {
            requestBody.put("role_id", command.roleId());
        }
        if (command.useKnowledgeGraph() != null) {
            requestBody.put("use_knowledge_graph", command.useKnowledgeGraph());
        }

        return transport.postJson("/rag/query", requestBody, RagQueryResult.class);
    }

    @Override
    public String uploadDocument(DocumentUpload upload) {
        MultipartBodyBuilder builder = new MultipartBodyBuilder();
        MediaType contentType = upload.contentType() != null
                ? MediaType.parseMediaType(upload.contentType())
                : MediaType.APPLICATION_OCTET_STREAM;
        builder.part("file", upload.content())
                .filename(upload.filename())
                .contentType(contentType);
        if (upload.roleId() != null && !upload.roleId().isBlank()) {
            builder.part("role_id", upload.roleId());
        }

        Map<String, Object> response = transport.postMultipart(
                "/rag/documents", builder.build(), TransportTypes.MAP);
        return response == null ? null : (String) response.get("document_id");
    }

    @Override
    public Map<String, Object> listDocuments(String roleId) {
        return transport.get(uriBuilder -> {
            UriBuilder builder = uriBuilder.path("/rag/documents");
            if (roleId != null && !roleId.isBlank()) {
                builder.queryParam("role_id", roleId);
            }
            return builder.build();
        }, TransportTypes.MAP);
    }

    @Override
    public void deleteDocument(String docId) {
        transport.delete("/rag/documents/" + docId, TransportTypes.MAP);
    }
}
