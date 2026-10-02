package com.kinlin.ai.projection.knowledgegraph;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.controller.KnowledgeGraphController;
import com.kinlin.ai.projection.knowledgegraph.mapper.KnowledgeQueryMapper;
import com.kinlin.ai.service.KnowledgeGraphService;
import org.junit.jupiter.api.Test;
import java.util.List;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class KnowledgeQueryMapperTest {
    private final ObjectMapper json = new ObjectMapper();
    @Test
    void entityKeepsExistingPublicDetailsWithoutArbitraryProperties() throws Exception {
        var wire = Map.<String, Object>of("entity", Map.of("id", "e1", "type", "person", "relations", List.of(
                Map.of("target", "e2", "relation", "works_at", "weight", 1.0)),
                "properties", Map.of("name", "公开姓名", "role_id", "r1", "runtime", "SECRET")),
                "related_entities", List.of(Map.of("entity", "e2", "relation", "works_at", "weight", 1.0,
                        "properties", Map.of("name", "公开机构", "internal", "SECRET"))));
        var result = json.valueToTree(KnowledgeQueryMapper.entity(wire));
        assertEquals("公开姓名", result.at("/data/entity/properties/name").textValue());
        assertEquals("e2", result.at("/data/entity/relations/0/target").textValue());
        assertFalse(result.toString().contains("SECRET"));
        var service = mock(KnowledgeGraphService.class);
        when(service.getEntityInfo("e1", null, 10)).thenReturn(wire);
        org.springframework.test.web.servlet.setup.MockMvcBuilders.standaloneSetup(new KnowledgeGraphController(service))
                .build().perform(get("/api/knowledge-graph/entity/e1"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.entity.properties.name").value("公开姓名"));
    }
    @Test
    void reasoningPathsKeepPairShapeOrderAndExistingErrorEnvelope() throws Exception {
        var paths = List.of(List.of(List.of("works_at", "e2"), List.of("located_in", "e3")));
        var result = json.valueToTree(KnowledgeQueryMapper.reason(Map.of("reasoning_paths", paths,
                "conclusions", List.of("公开结论"), "entities", List.of(), "relations", List.of("works_at"))));
        assertEquals(json.valueToTree(paths), result.at("/data/reasoning_paths"));
        assertThrows(IllegalArgumentException.class, () -> KnowledgeQueryMapper.reason(Map.of("reasoning_paths", List.of(List.of(List.of("bad"))))));
        assertEquals(json.valueToTree(Map.of("success", true, "data", Map.of("error", "existing error"))),
                json.valueToTree(KnowledgeQueryMapper.reason(Map.of("error", "existing error"))));
        assertEquals(json.valueToTree(Map.of("success", true, "data", Map.of())), json.valueToTree(KnowledgeQueryMapper.entity(Map.of())));
    }
    @Test
    void searchDropsUntrustedMetadataAndKeepsRequestForwardingAndFallback() throws Exception {
        var source = Map.<String, Object>of("kg_results", List.of(), "entities", List.of(), "vector_results", List.of(
                Map.of("content", "完整公开正文", "score", 0.9, "metadata", Map.of("internal", "SECRET"))),
                "fused_results", List.of(Map.of("source", "vector_db", "content", "完整公开正文", "score", 0.9,
                        "metadata", Map.of("internal", "SECRET"))));
        var result = json.valueToTree(KnowledgeQueryMapper.search(source));
        assertEquals("完整公开正文", result.at("/data/vector_results/0/content").textValue());
        assertFalse(result.toString().contains("SECRET"));
        var service = mock(KnowledgeGraphService.class);
        when(service.hybridSearch("question", List.of(), 3)).thenReturn(source);
        when(service.reasonWithKnowledgeGraph("question")).thenReturn(Map.of("error", "existing error"));
        var mvc = org.springframework.test.web.servlet.setup.MockMvcBuilders.standaloneSetup(new KnowledgeGraphController(service)).build();
        mvc.perform(post("/api/knowledge-graph/search").param("question", "question").param("topK", "3")
                .contentType("application/json").content("[]")).andExpect(status().isOk())
                .andExpect(jsonPath("$.data.vector_results[0].content").value("完整公开正文"));
        verify(service).hybridSearch("question", List.of(), 3);
        mvc.perform(post("/api/knowledge-graph/reason").param("question", "question"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.error").value("existing error"));
    }
}
