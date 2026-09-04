package com.kinlin.ai.service;

import com.kinlin.ai.dto.RecommendationContextRequest;
import com.kinlin.ai.dto.RecommendationItem;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class RecommendationServiceTest {

    private final RecommendationService recommendationService = new RecommendationService();

    @Test
    void generateContextualRecommendations_emptyLawyerChat_returnsStructuredDefaults() {
        RecommendationContextRequest request = new RecommendationContextRequest();
        request.setRoleName("律师");
        request.setScope("chat");

        List<RecommendationItem> items = recommendationService.generateContextualRecommendations(request);

        assertFalse(items.isEmpty());
        assertTrue(items.size() <= 5);
        assertEquals("chat", items.get(0).getScope());
        assertEquals("fill_input", items.get(0).getTargetAction());
        assertNotNull(items.get(0).getText());
        assertFalse(items.get(0).getText().isBlank());
        assertNotNull(items.get(0).getReason());
        assertTrue(items.get(0).getConfidence() > 0);
    }

    @Test
    void generateContextualRecommendations_contractWorkbench_prefersClauseAndRiskSuggestions() {
        RecommendationContextRequest request = new RecommendationContextRequest();
        request.setRoleName("律师");
        request.setScope("workbench");
        request.setScene("clause");
        request.setCurrentInput("请帮我补充软件开发合同的验收标准和知识产权条款");
        request.setConversationHistory(List.of(
                "需要起草软件开发合同",
                "重点补充交付、验收和知识产权"
        ));

        List<RecommendationItem> items = recommendationService.generateContextualRecommendations(request);

        assertFalse(items.isEmpty());
        assertTrue(items.stream().allMatch(item -> "workbench".equals(item.getScope())));
        assertTrue(items.stream().anyMatch(item -> item.getText().contains("验收") || item.getText().contains("知识产权")));
        assertTrue(items.stream().anyMatch(item -> item.getTargetAction().equals("fill_input")));
    }
}
