package com.kinlin.ai.infrastructure.http;

import com.kinlin.ai.client.KnowledgeGraphClient;
import com.kinlin.ai.dto.KnowledgeGraphRequest;
import org.springframework.stereotype.Component;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * WebClient implementation of the knowledge-graph capability
 * ({@code /api/knowledge-graph/**} family). Unwraps the upstream
 * {@code success/data} envelope; graph payloads stay dynamic maps.
 */
@Component
public class WebClientKnowledgeGraphClient implements KnowledgeGraphClient {

    private final PlatformAiTransport transport;

    public WebClientKnowledgeGraphClient(PlatformAiTransport transport) {
        this.transport = transport;
    }

    @Override
    public Map<String, Object> buildKnowledgeGraph(List<KnowledgeGraphRequest.DocumentInfo> documents, String roleId) {
        List<Map<String, Object>> docs = documents.stream()
                .map(doc -> {
                    Map<String, Object> docMap = new HashMap<>();
                    docMap.put("doc_id", doc.getDocId());
                    docMap.put("text", doc.getText());
                    if (doc.getMetadata() != null) {
                        docMap.put("metadata", doc.getMetadata());
                    }
                    return docMap;
                })
                .collect(Collectors.toList());

        Map<String, Object> requestBody = new HashMap<>();
        requestBody.put("documents", docs);
        if (roleId != null && !roleId.isBlank()) {
            requestBody.put("role_id", roleId);
        }

        return unwrap(transport.postJson("/api/knowledge-graph/build", requestBody, TransportTypes.MAP));
    }

    @Override
    public Map<String, Object> hybridSearch(String question, List<Map<String, Object>> vectorDbResults, Integer topK) {
        Map<String, Object> requestBody = new HashMap<>();
        requestBody.put("question", question);
        requestBody.put("vector_db_results", vectorDbResults);
        requestBody.put("top_k", topK != null ? topK : 5);

        return unwrap(transport.postJson("/api/knowledge-graph/search", requestBody, TransportTypes.MAP));
    }

    @Override
    public Map<String, Object> reasonWithKnowledgeGraph(String question) {
        Map<String, Object> requestBody = new HashMap<>();
        requestBody.put("question", question);

        return unwrap(transport.postJson("/api/knowledge-graph/reason", requestBody, TransportTypes.MAP));
    }

    @Override
    public Map<String, Object> getGraphStats() {
        return unwrap(transport.get("/api/knowledge-graph/stats", TransportTypes.MAP));
    }

    @Override
    public Map<String, Object> getEntityInfo(String entityId, String relation, Integer limit) {
        StringBuilder uriBuilder = new StringBuilder("/api/knowledge-graph/entity/").append(entityId);
        if (relation != null) {
            uriBuilder.append("?relation=").append(relation);
        }
        if (limit != null) {
            uriBuilder.append(relation != null ? "&" : "?").append("limit=").append(limit);
        }

        return unwrap(transport.get(uriBuilder.toString(), TransportTypes.MAP));
    }

    @Override
    public Map<String, Object> getGraphData(String roleId) {
        StringBuilder uriBuilder = new StringBuilder("/api/knowledge-graph/graph-data");
        if (roleId != null && !roleId.isEmpty()) {
            uriBuilder.append("?role_id=").append(roleId);
        }

        Map<String, Object> responseMap = transport.get(uriBuilder.toString(), TransportTypes.MAP);
        if (responseMap != null && Boolean.TRUE.equals(responseMap.get("success"))) {
            Map<String, Object> data = dataOf(responseMap);
            return data != null ? data : new HashMap<>();
        }
        return new HashMap<>();
    }

    private static Map<String, Object> unwrap(Map<String, Object> responseMap) {
        if (responseMap != null && Boolean.TRUE.equals(responseMap.get("success"))) {
            return dataOf(responseMap);
        }
        return new HashMap<>();
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> dataOf(Map<String, Object> responseMap) {
        return (Map<String, Object>) responseMap.get("data");
    }
}
