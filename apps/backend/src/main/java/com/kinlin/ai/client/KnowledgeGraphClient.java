package com.kinlin.ai.client;

import com.kinlin.ai.dto.KnowledgeGraphRequest;

import java.util.List;
import java.util.Map;

/**
 * What the Java platform needs from the Python knowledge-graph capability
 * ({@code /api/knowledge-graph/**} family).
 *
 * <p>Graph payloads are intentionally dynamic {@code Map} projections (N1.2 owns
 * systematic typing); the {@code success/data} envelope is unwrapped here so callers
 * receive the data payload directly.</p>
 */
public interface KnowledgeGraphClient {

    Map<String, Object> buildKnowledgeGraph(List<KnowledgeGraphRequest.DocumentInfo> documents, String roleId);

    Map<String, Object> hybridSearch(String question, List<Map<String, Object>> vectorDbResults, Integer topK);

    Map<String, Object> reasonWithKnowledgeGraph(String question);

    Map<String, Object> getGraphStats();

    Map<String, Object> getEntityInfo(String entityId, String relation, Integer limit);

    Map<String, Object> getGraphData(String roleId);
}
