package com.kinlin.ai.service;

import com.kinlin.ai.client.PlatformAiClientException;
import com.kinlin.ai.client.RagClient;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.Map;

/**
 * RAG应用服务：RAG 能力的业务编排与 fallback 决策。
 *
 * <p>HTTP 细节（endpoint、序列化、超时、transport 错误分类）已下沉到
 * {@link RagClient}；本层只决定 transport 失败时的业务结果（固定文案 fallback /
 * 业务异常 / 静默忽略），用户可见行为与分层前保持一致。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class RagService {

    private final RagClient ragClient;

    /**
     * RAG查询
     */
    public RagClient.RagQueryResult query(String query, Integer topK, String contextId) {
        return query(query, topK, contextId, null, null);
    }

    /**
     * RAG查询
     */
    public RagClient.RagQueryResult query(String query, Integer topK, String contextId, String roleId, Boolean useKnowledgeGraph) {
        try {
            return ragClient.query(new RagClient.RagQueryCommand(query, topK, contextId, roleId, useKnowledgeGraph));
        } catch (PlatformAiClientException e) {
            log.error("RAG查询失败，Python服务可能未启动", e);
            // 返回一个默认响应而不是抛出异常
            return new RagClient.RagQueryResult(
                    "抱歉，RAG服务当前不可用，请稍后重试。",
                    new ArrayList<>(),
                    0.0
            );
        }
    }

    /**
     * 上传文档
     */
    public String uploadDocument(byte[] fileData, String filename) {
        return upload(new RagClient.DocumentUpload(new ByteArrayResource(fileData), filename, null, null));
    }

    /**
     * 上传文档（使用MultipartFile）
     */
    public String uploadDocument(MultipartFile file) {
        return uploadDocument(file, null);
    }

    /**
     * 上传文档（使用MultipartFile）
     */
    public String uploadDocument(MultipartFile file, String roleId) {
        return upload(new RagClient.DocumentUpload(
                file.getResource(),
                file.getOriginalFilename(),
                file.getContentType() != null ? file.getContentType() : "application/octet-stream",
                roleId
        ));
    }

    private String upload(RagClient.DocumentUpload upload) {
        try {
            try {
                return ragClient.uploadDocument(upload);
            } catch (PlatformAiClientException e) {
                log.error("文档上传失败，Python服务可能未启动", e);
                // J1.3：用户可见文案不暴露实现细节（Python/端口）；外层统一加"文档上传失败"前缀
                throw new RuntimeException("RAG服务当前不可用，请稍后重试。");
            }
        } catch (RuntimeException e) {
            log.error("文档上传失败", e);
            // 既有可观察行为：外层包装保持单一"文档上传失败: "前缀
            throw new RuntimeException("文档上传失败: " + e.getMessage());
        }
    }

    /**
     * 获取文档列表
     */
    public Map<String, Object> listDocuments() {
        return listDocuments(null);
    }

    /**
     * 获取文档列表
     */
    public Map<String, Object> listDocuments(String roleId) {
        try {
            return ragClient.listDocuments(roleId);
        } catch (PlatformAiClientException e) {
            log.error("获取文档列表失败，Python服务可能未启动", e);
            // 返回空列表而不是抛出异常
            Map<String, Object> fallbackResponse = new HashMap<>();
            fallbackResponse.put("documents", new ArrayList<>());
            fallbackResponse.put("message", "RAG服务当前不可用，请稍后重试。");
            return fallbackResponse;
        }
    }

    /**
     * 删除文档
     */
    public void deleteDocument(String docId) {
        try {
            ragClient.deleteDocument(docId);
        } catch (PlatformAiClientException e) {
            log.error("删除文档失败，Python服务可能未启动", e);
            // 不抛出异常，只记录日志
            log.warn("删除文档操作失败，但继续执行: {}", e.getMessage());
        }
    }
}
