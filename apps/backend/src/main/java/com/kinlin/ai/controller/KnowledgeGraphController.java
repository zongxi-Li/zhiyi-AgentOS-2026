package com.kinlin.ai.controller;

import com.kinlin.ai.dto.KnowledgeGraphRequest;
import com.kinlin.ai.projection.knowledgegraph.dto.KnowledgeGraphEnvelopeQuery;
import com.kinlin.ai.projection.knowledgegraph.mapper.KnowledgeGraphProjectionMapper;
import com.kinlin.ai.projection.knowledgegraph.dto.KnowledgeQuery;
import com.kinlin.ai.projection.knowledgegraph.mapper.KnowledgeQueryMapper;
import com.kinlin.ai.service.KnowledgeGraphService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 知识图谱控制器
 */
@Slf4j
@RestController
@RequestMapping("/api/knowledge-graph")
@RequiredArgsConstructor
public class KnowledgeGraphController {

    private final KnowledgeGraphService knowledgeGraphService;

    private ResponseEntity<Map<String, Object>> wrapSuccess(Map<String, Object> data) {
        Map<String, Object> response = new HashMap<>();
        response.put("success", true);
        response.put("data", data);
        return ResponseEntity.ok(response);
    }

    /**
     * 从文档构建知识图谱
     */
    @PostMapping("/build")
    public ResponseEntity<Map<String, Object>> buildKnowledgeGraph(
            @Valid @RequestBody KnowledgeGraphRequest request
    ) {
        Map<String, Object> result = knowledgeGraphService.buildKnowledgeGraph(request.getDocuments(), request.getRoleId());
        return wrapSuccess(result);
    }

    /**
     * 混合检索：知识图谱 + 向量数据库
     */
    @PostMapping("/search")
    public ResponseEntity<KnowledgeQuery.SearchEnvelope> hybridSearch(
            @RequestParam("question") String question,
            @RequestBody List<Map<String, Object>> vectorDbResults,
            @RequestParam(value = "topK", defaultValue = "5") Integer topK
    ) {
        Map<String, Object> result = knowledgeGraphService.hybridSearch(question, vectorDbResults, topK);
        return ResponseEntity.ok(KnowledgeQueryMapper.search(result));
    }

    /**
     * 基于知识图谱进行推理
     */
    @PostMapping("/reason")
    public ResponseEntity<KnowledgeQuery.ReasonEnvelope> reasonWithKnowledgeGraph(
            @RequestParam("question") String question
    ) {
        Map<String, Object> result = knowledgeGraphService.reasonWithKnowledgeGraph(question);
        return ResponseEntity.ok(KnowledgeQueryMapper.reason(result));
    }

    /**
     * 获取知识图谱统计信息
     */
    @GetMapping("/stats")
    public ResponseEntity<KnowledgeGraphEnvelopeQuery.StatsEnvelope> getGraphStats() {
        return ResponseEntity.ok(
                KnowledgeGraphProjectionMapper.stats(knowledgeGraphService.getGraphStats()));
    }

    /**
     * 查询实体相关信息
     */
    @GetMapping("/entity/{entityId}")
    public ResponseEntity<KnowledgeQuery.EntityEnvelope> getEntityInfo(
            @PathVariable String entityId,
            @RequestParam(value = "relation", required = false) String relation,
            @RequestParam(value = "limit", defaultValue = "10") Integer limit
    ) {
        Map<String, Object> result = knowledgeGraphService.getEntityInfo(entityId, relation, limit);
        return ResponseEntity.ok(KnowledgeQueryMapper.entity(result));
    }

    /**
     * 获取完整的知识图谱数据（用于可视化）
     */
    @GetMapping("/graph-data")
    public ResponseEntity<KnowledgeGraphEnvelopeQuery.GraphDataEnvelope> getGraphData(
            @RequestParam(value = "role_id", required = false) String roleId
    ) {
        return ResponseEntity.ok(
                KnowledgeGraphProjectionMapper.graphData(knowledgeGraphService.getGraphData(roleId)));
    }
}
