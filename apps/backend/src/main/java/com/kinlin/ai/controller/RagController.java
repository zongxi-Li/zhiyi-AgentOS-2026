package com.kinlin.ai.controller;

import com.kinlin.ai.client.RagClient;
import com.kinlin.ai.projection.rag.dto.RagDocumentPageQuery;
import com.kinlin.ai.projection.rag.dto.RagQueryResponseQuery;
import com.kinlin.ai.projection.rag.mapper.RagProjectionMapper;
import com.kinlin.ai.service.RagService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

/**
 * RAG控制器
 */
@RestController
@RequestMapping("/rag")
@RequiredArgsConstructor
public class RagController {

    private final RagService ragService;

    /**
     * RAG查询
     */
    @PostMapping("/query")
    public ResponseEntity<RagQueryResponseQuery> query(
            @RequestBody Map<String, Object> request
    ) {
        String query = (String) request.get("query");
        Integer topK = request.get("top_k") != null ?
                ((Number) request.get("top_k")).intValue() : 5;
        String contextId = request.get("context_id") != null ?
                (String) request.get("context_id") : null;
        String roleId = request.get("role_id") != null ?
                request.get("role_id").toString() : null;
        Boolean useKnowledgeGraph = request.get("use_knowledge_graph") != null ?
                Boolean.valueOf(request.get("use_knowledge_graph").toString()) : null;

        RagClient.RagQueryResult result = ragService.query(query, topK, contextId, roleId, useKnowledgeGraph);
        return ResponseEntity.ok(RagProjectionMapper.query(result.answer(), result.sources(), result.confidence()));
    }

    /**
     * 上传文档
     */
    @PostMapping("/documents")
    public ResponseEntity<Map<String, String>> uploadDocument(
            @RequestParam("file") org.springframework.web.multipart.MultipartFile file,
            @RequestParam(value = "role_id", required = false) String roleId
    ) {
        try {
            String documentId = ragService.uploadDocument(file, roleId);
            return ResponseEntity.ok(Map.of("document_id", documentId));
        } catch (Exception e) {
            return ResponseEntity.internalServerError()
                    .body(Map.of("error", e.getMessage()));
        }
    }
    
    /**
     * 获取文档列表
     */
    @GetMapping("/documents")
    public ResponseEntity<com.kinlin.ai.projection.common.dto.QueryResponse> listDocuments(
            @RequestParam(value = "role_id", required = false) String roleId
    ) {
        try {
            return ResponseEntity.ok(RagProjectionMapper.documents(ragService.listDocuments(roleId)));
        } catch (Exception e) {
            return ResponseEntity.internalServerError()
                    .body(new com.kinlin.ai.projection.rag.dto.RagErrorResponse(e.getMessage()));
        }
    }
    
    /**
     * 删除文档
     */
    @DeleteMapping("/documents/{docId}")
    public ResponseEntity<Map<String, String>> deleteDocument(@PathVariable String docId) {
        try {
            ragService.deleteDocument(docId);
            return ResponseEntity.ok(Map.of("message", "文档删除成功", "doc_id", docId));
        } catch (Exception e) {
            return ResponseEntity.internalServerError()
                    .body(Map.of("error", e.getMessage()));
        }
    }
}

