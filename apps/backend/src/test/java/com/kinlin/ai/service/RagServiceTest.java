package com.kinlin.ai.service;

import com.kinlin.ai.client.PlatformAiClientException;
import com.kinlin.ai.client.RagClient;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.mock.web.MockMultipartFile;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/**
 * RagService单元测试（应用层 fallback 表征：transport 失败时的既有用户可见行为）
 */
@ExtendWith(MockitoExtension.class)
class RagServiceTest {

    @Mock
    private RagClient ragClient;

    private RagService ragService;

    @BeforeEach
    void setUp() {
        ragService = new RagService(ragClient);
    }

    @Test
    void testQuery_Success() {
        // Given
        String query = "测试查询";
        Integer topK = 5;
        String contextId = "context-123";

        RagClient.RagQueryResult expectedResponse = new RagClient.RagQueryResult(
                "这是回答",
                List.of(Map.of("doc_id", "doc1", "filename", "test.txt")),
                0.95
        );
        when(ragClient.query(any(RagClient.RagQueryCommand.class))).thenReturn(expectedResponse);

        // When
        RagClient.RagQueryResult result = ragService.query(query, topK, contextId);

        // Then
        assertNotNull(result);
        assertEquals("这是回答", result.answer());
        assertEquals(0.95, result.confidence());
        assertFalse(result.sources().isEmpty());
    }

    @Test
    void testQuery_WithNullTopK() {
        // Given
        RagClient.RagQueryResult expectedResponse = new RagClient.RagQueryResult(
                "回答",
                List.of(),
                0.9
        );
        when(ragClient.query(any(RagClient.RagQueryCommand.class))).thenReturn(expectedResponse);

        // When
        RagClient.RagQueryResult result = ragService.query("测试查询", null, null);

        // Then
        assertNotNull(result);
        verify(ragClient).query(argThat(command ->
                command.topK() == null && "测试查询".equals(command.query())));
    }

    @Test
    void testQuery_TransportFailureKeepsFrozenFallbackText() {
        // Given：Python 不可用（表征冻结：固定文案、空来源、confidence 0）
        when(ragClient.query(any(RagClient.RagQueryCommand.class)))
                .thenThrow(new PlatformAiClientException(
                        PlatformAiClientException.Type.UNAVAILABLE, "Connection refused"));

        // When
        RagClient.RagQueryResult result = ragService.query("测试查询", 5, null);

        // Then
        assertNotNull(result);
        assertEquals("抱歉，RAG服务当前不可用，请稍后重试。", result.answer());
        assertEquals(0.0, result.confidence());
        assertTrue(result.sources().isEmpty());
    }

    @Test
    void testUploadDocument_TransportFailureKeepsSingleStablePrefix() {
        // Given：J1.3 文案清理——内层稳定文案，外层统一"文档上传失败"前缀（不再双重前缀）
        when(ragClient.uploadDocument(any(RagClient.DocumentUpload.class)))
                .thenThrow(new PlatformAiClientException(
                        PlatformAiClientException.Type.UNAVAILABLE, "Connection refused"));

        // When & Then
        RuntimeException error = assertThrows(RuntimeException.class,
                () -> ragService.uploadDocument("hello".getBytes(), "notes.txt"));
        assertEquals("文档上传失败: RAG服务当前不可用，请稍后重试。",
                error.getMessage());
    }

    @Test
    void testUploadDocument_MultipartFilePassesResourceAndContentType() {
        // Given
        MockMultipartFile file = new MockMultipartFile(
                "file", "notes.txt", "text/plain", "hello".getBytes());
        when(ragClient.uploadDocument(any(RagClient.DocumentUpload.class))).thenReturn("doc-123");

        // When
        String documentId = ragService.uploadDocument(file, "role-1");

        // Then
        assertEquals("doc-123", documentId);
        verify(ragClient).uploadDocument(argThat(upload ->
                "notes.txt".equals(upload.filename())
                        && "text/plain".equals(upload.contentType())
                        && "role-1".equals(upload.roleId())));
    }

    @Test
    void testListDocuments_Success() {
        // Given
        Map<String, Object> expectedResponse = new HashMap<>();
        expectedResponse.put("documents", List.of());
        expectedResponse.put("count", 0);
        when(ragClient.listDocuments(null)).thenReturn(expectedResponse);

        // When
        Map<String, Object> result = ragService.listDocuments();

        // Then
        assertNotNull(result);
        assertTrue(result.containsKey("documents"));
        assertTrue(result.containsKey("count"));
    }

    @Test
    void testListDocuments_TransportFailureKeepsFrozenFallback() {
        // Given
        when(ragClient.listDocuments(any()))
                .thenThrow(new PlatformAiClientException(
                        PlatformAiClientException.Type.TIMEOUT, "timeout"));

        // When
        Map<String, Object> result = ragService.listDocuments("role-1");

        // Then
        assertEquals(new HashMap<>(Map.of(
                "documents", List.of(),
                "message", "RAG服务当前不可用，请稍后重试。")), result);
    }

    @Test
    void testDeleteDocument_Success() {
        // Given
        String docId = "doc-123";
        doNothing().when(ragClient).deleteDocument(docId);

        // When & Then
        assertDoesNotThrow(() -> ragService.deleteDocument(docId));
    }

    @Test
    void testDeleteDocument_TransportFailureIsSwallowedLikeBefore() {
        // Given：表征冻结——删除失败静默继续（既有行为）
        doThrow(new PlatformAiClientException(
                PlatformAiClientException.Type.UNAVAILABLE, "Connection refused"))
                .when(ragClient).deleteDocument("doc-123");

        // When & Then
        assertDoesNotThrow(() -> ragService.deleteDocument("doc-123"));
    }
}
