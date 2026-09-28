package com.kinlin.ai.service;

import com.kinlin.ai.client.KnowledgeGraphClient;
import com.kinlin.ai.client.PlatformAiClientException;
import com.kinlin.ai.dto.KnowledgeGraphRequest;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 知识图谱应用服务：知识图谱能力的业务编排与 fallback 决策。
 *
 * <p>HTTP 细节与 {@code success/data} 信封解包已下沉到 {@link KnowledgeGraphClient}；
 * transport 失败时保持既有用户可见行为（error Map / 空 Map）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class KnowledgeGraphService {

    private final KnowledgeGraphClient knowledgeGraphClient;

    /**
     * 从文档构建知识图谱
     */
    public Map<String, Object> buildKnowledgeGraph(List<KnowledgeGraphRequest.DocumentInfo> documents) {
        return buildKnowledgeGraph(documents, null);
    }

    /**
     * 从文档构建知识图谱
     */
    public Map<String, Object> buildKnowledgeGraph(List<KnowledgeGraphRequest.DocumentInfo> documents, String roleId) {
        try {
            return knowledgeGraphClient.buildKnowledgeGraph(documents, roleId);
        } catch (PlatformAiClientException e) {
            log.error("构建知识图谱失败", e);
            Map<String, Object> errorResponse = new HashMap<>();
            errorResponse.put("error", "构建知识图谱失败: " + e.getMessage());
            return errorResponse;
        }
    }

    /**
     * 混合检索：知识图谱 + 向量数据库
     */
    public Map<String, Object> hybridSearch(String question, List<Map<String, Object>> vectorDbResults, Integer topK) {
        try {
            return knowledgeGraphClient.hybridSearch(question, vectorDbResults, topK);
        } catch (PlatformAiClientException e) {
            log.error("混合检索失败", e);
            Map<String, Object> errorResponse = new HashMap<>();
            errorResponse.put("error", "混合检索失败: " + e.getMessage());
            return errorResponse;
        }
    }

    /**
     * 基于知识图谱进行推理
     */
    public Map<String, Object> reasonWithKnowledgeGraph(String question) {
        try {
            return knowledgeGraphClient.reasonWithKnowledgeGraph(question);
        } catch (PlatformAiClientException e) {
            log.error("知识推理失败", e);
            Map<String, Object> errorResponse = new HashMap<>();
            errorResponse.put("error", "知识推理失败: " + e.getMessage());
            return errorResponse;
        }
    }

    /**
     * 获取知识图谱统计信息
     */
    public Map<String, Object> getGraphStats() {
        try {
            return knowledgeGraphClient.getGraphStats();
        } catch (PlatformAiClientException e) {
            log.error("获取知识图谱统计信息失败", e);
            return new HashMap<>();
        }
    }

    /**
     * 查询实体相关信息
     */
    public Map<String, Object> getEntityInfo(String entityId, String relation, Integer limit) {
        try {
            return knowledgeGraphClient.getEntityInfo(entityId, relation, limit);
        } catch (PlatformAiClientException e) {
            log.error("查询实体信息失败", e);
            Map<String, Object> errorResponse = new HashMap<>();
            errorResponse.put("error", "查询实体信息失败: " + e.getMessage());
            return errorResponse;
        }
    }

    /**
     * 获取完整的知识图谱数据（用于可视化）
     */
    public Map<String, Object> getGraphData(String roleId) {
        try {
            return knowledgeGraphClient.getGraphData(roleId);
        } catch (PlatformAiClientException e) {
            log.error("获取知识图谱数据失败", e);
            Map<String, Object> errorResponse = new HashMap<>();
            errorResponse.put("error", "获取知识图谱数据失败: " + e.getMessage());
            return errorResponse;
        }
    }
}
