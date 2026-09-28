package com.kinlin.ai.service;

import com.kinlin.ai.client.KnowledgeGraphClient;
import com.kinlin.ai.client.PlatformAiClientException;
import com.kinlin.ai.dto.KnowledgeGraphRequest;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;

/**
 * KnowledgeGraphService单元测试（应用层 fallback 表征：transport 失败时的既有用户可见行为）
 */
@ExtendWith(MockitoExtension.class)
class KnowledgeGraphServiceTest {

    @Mock
    private KnowledgeGraphClient knowledgeGraphClient;

    private KnowledgeGraphService knowledgeGraphService;

    @BeforeEach
    void setUp() {
        knowledgeGraphService = new KnowledgeGraphService(knowledgeGraphClient);
    }

    @Test
    void testBuildKnowledgeGraph_Success() {
        // Arrange
        List<KnowledgeGraphRequest.DocumentInfo> documents = new ArrayList<>();
        KnowledgeGraphRequest.DocumentInfo doc = new KnowledgeGraphRequest.DocumentInfo();
        doc.setDocId("doc1");
        doc.setText("张三是一名律师");
        documents.add(doc);

        when(knowledgeGraphClient.buildKnowledgeGraph(documents, null))
                .thenReturn(Map.of("entities_count", 10, "triples_count", 20));

        // Act
        Map<String, Object> result = knowledgeGraphService.buildKnowledgeGraph(documents);

        // Assert
        assertNotNull(result);
        assertEquals(10, result.get("entities_count"));
    }

    @Test
    void testHybridSearch_Success() {
        // Arrange
        String question = "律师有哪些？";
        List<Map<String, Object>> vectorResults = new ArrayList<>();
        Integer topK = 5;

        when(knowledgeGraphClient.hybridSearch(question, vectorResults, topK))
                .thenReturn(Map.of("results", new ArrayList<>()));

        // Act
        Map<String, Object> result = knowledgeGraphService.hybridSearch(question, vectorResults, topK);

        // Assert
        assertNotNull(result);
    }

    @Test
    void testReasonWithKnowledgeGraph_Success() {
        // Arrange
        String question = "张三和李四的关系是什么？";

        when(knowledgeGraphClient.reasonWithKnowledgeGraph(question))
                .thenReturn(Map.of("reasoning_result", "同事关系"));

        // Act
        Map<String, Object> result = knowledgeGraphService.reasonWithKnowledgeGraph(question);

        // Assert
        assertNotNull(result);
        assertEquals("同事关系", result.get("reasoning_result"));
    }

    @Test
    void testGetGraphStats_Success() {
        // Arrange
        when(knowledgeGraphClient.getGraphStats()).thenReturn(Map.of("entities_count", 10));

        // Act
        Map<String, Object> result = knowledgeGraphService.getGraphStats();

        // Assert
        assertNotNull(result);
        assertEquals(10, result.get("entities_count"));
    }

    @Test
    void testBuildKnowledgeGraph_TransportFailureKeepsFrozenErrorMap() {
        // Arrange：表征冻结——error Map 携带既有前缀文案
        when(knowledgeGraphClient.buildKnowledgeGraph(any(), anyString()))
                .thenThrow(new PlatformAiClientException(
                        PlatformAiClientException.Type.UNAVAILABLE, "Connection refused"));

        // Act
        Map<String, Object> result = knowledgeGraphService.buildKnowledgeGraph(new ArrayList<>(), "role-1");

        // Assert
        assertEquals("构建知识图谱失败: Connection refused", result.get("error"));
    }

    @Test
    void testGetGraphStats_TransportFailureKeepsSilentEmptyMap() {
        // Arrange：表征冻结——stats 失败吞错返回空 Map
        when(knowledgeGraphClient.getGraphStats())
                .thenThrow(new PlatformAiClientException(
                        PlatformAiClientException.Type.TIMEOUT, "Did not observe any item"));

        // Act
        Map<String, Object> result = knowledgeGraphService.getGraphStats();

        // Assert
        assertTrue(result.isEmpty());
    }
}
