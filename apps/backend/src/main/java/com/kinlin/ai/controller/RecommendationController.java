package com.kinlin.ai.controller;

import com.kinlin.ai.dto.RecommendationContextRequest;
import com.kinlin.ai.dto.RecommendationItem;
import com.kinlin.ai.service.RecommendationService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 推荐控制器
 */
@RestController
@RequestMapping("/recommendations")
@RequiredArgsConstructor
public class RecommendationController {

    private final RecommendationService recommendationService;

    /**
     * 获取推荐问题
     *
     * @param conversationHistory 对话历史（JSON数组）
     * @param roleName 角色名称（可选）
     * @return 推荐问题列表
     */
    @PostMapping("/questions")
    public ResponseEntity<List<String>> getRecommendations(
            @RequestBody(required = false) List<String> conversationHistory,
            @RequestParam(required = false) String roleName
    ) {
        try {
            List<String> recommendations = recommendationService.generateRecommendations(
                    conversationHistory != null ? conversationHistory : List.of(),
                    roleName
            );
            return ResponseEntity.ok(recommendations);
        } catch (Exception e) {
            return ResponseEntity.internalServerError().build();
        }
    }

    @PostMapping("/contextual")
    public ResponseEntity<List<RecommendationItem>> getContextualRecommendations(
            @RequestBody(required = false) RecommendationContextRequest request
    ) {
        try {
            List<RecommendationItem> recommendations = recommendationService.generateContextualRecommendations(
                    request == null ? new RecommendationContextRequest() : request
            );
            return ResponseEntity.ok(recommendations);
        } catch (Exception e) {
            return ResponseEntity.internalServerError().build();
        }
    }
}

