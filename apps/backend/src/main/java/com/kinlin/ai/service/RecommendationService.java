package com.kinlin.ai.service;

import com.kinlin.ai.dto.RecommendationContextRequest;
import com.kinlin.ai.dto.RecommendationItem;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.stream.Collectors;

/**
 * 推荐服务
 * 基于对话上下文生成推荐问题
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class RecommendationService {

    /**
     * 基于对话上下文生成推荐问题
     *
     * @param conversationHistory 对话历史（最近的几条消息）
     * @param roleName 当前角色名称（可选）
     * @return 推荐问题列表
     */
    public List<String> generateRecommendations(List<String> conversationHistory, String roleName) {
        RecommendationContextRequest request = new RecommendationContextRequest();
        request.setRoleName(roleName);
        request.setScope("chat");
        request.setConversationHistory(conversationHistory);
        return generateContextualRecommendations(request).stream()
                .map(RecommendationItem::getText)
                .distinct()
                .limit(5)
                .collect(Collectors.toList());
    }

    public List<RecommendationItem> generateContextualRecommendations(RecommendationContextRequest request) {
        RecommendationContextRequest safeRequest = request == null ? new RecommendationContextRequest() : request;
        List<String> conversationHistory = safeRequest.getConversationHistory() == null
                ? List.of()
                : safeRequest.getConversationHistory();
        String roleName = safeRequest.getRoleName();
        String scope = normalizeScope(safeRequest.getScope());

        List<String> baseSuggestions = new ArrayList<>();
        String recentText = buildRecentText(conversationHistory, safeRequest.getCurrentInput(), safeRequest.getCurrentOutput());

        if (!recentText.isBlank()) {
            List<String> keywords = extractKeywords(recentText);
            baseSuggestions.addAll(generateQuestionsByKeywords(keywords));
            baseSuggestions.addAll(generateSceneRecommendations(safeRequest.getScene(), recentText));
        }

        if (baseSuggestions.size() < 3) {
            baseSuggestions.addAll(getDefaultRecommendations());
        }

        return baseSuggestions.stream()
                .filter(text -> text != null && !text.isBlank())
                .distinct()
                .limit(5)
                .map(text -> toRecommendationItem(text, scope, safeRequest.getScene(), roleName, recentText))
                .collect(Collectors.toList());
    }

    /**
     * 提取关键词
     */
    private List<String> extractKeywords(String text) {
        List<String> keywords = new ArrayList<>();
        
        // 常见问题关键词
        String[] questionWords = {"什么", "如何", "怎么", "为什么", "哪个", "哪些", "能否", "可以", "是否"};
        String[] topicWords = {"法律", "合同", "纠纷", "学习", "教育", "代码", "编程", "写作", "文章"};

        for (String word : questionWords) {
            if (text.contains(word)) {
                keywords.add(word);
            }
        }

        for (String word : topicWords) {
            if (text.contains(word)) {
                keywords.add(word);
            }
        }

        return keywords;
    }

    private String buildRecentText(List<String> conversationHistory, String currentInput, String currentOutput) {
        List<String> pieces = new ArrayList<>();
        if (conversationHistory != null && !conversationHistory.isEmpty()) {
            pieces.add(conversationHistory.stream().limit(4).collect(Collectors.joining(" ")));
        }
        if (currentInput != null && !currentInput.isBlank()) {
            pieces.add(currentInput);
        }
        if (currentOutput != null && !currentOutput.isBlank()) {
            pieces.add(currentOutput);
        }
        return pieces.stream()
                .filter(item -> item != null && !item.isBlank())
                .collect(Collectors.joining(" "));
    }

    /**
     * 基于关键词生成推荐问题
     */
    private List<String> generateQuestionsByKeywords(List<String> keywords) {
        List<String> questions = new ArrayList<>();

        if (keywords.isEmpty()) {
            return questions;
        }

        // 通用问题
        if (keywords.contains("什么")) {
            questions.add("能详细解释一下吗？");
        }
        if (keywords.contains("如何") || keywords.contains("怎么")) {
            questions.add("具体步骤是什么？");
        }
        if (keywords.contains("为什么")) {
            questions.add("有什么原因吗？");
        }

        return questions;
    }

    private List<String> generateSceneRecommendations(String scene, String text) {
        List<String> questions = new ArrayList<>();
        String normalizedScene = scene == null ? "" : scene.trim().toLowerCase(Locale.ROOT);
        String lowered = text == null ? "" : text.toLowerCase(Locale.ROOT);

        if (normalizedScene.equals("clause")) {
            if (lowered.contains("合同") || lowered.contains("验收")) {
                questions.add("补充阶段验收的判定标准");
                questions.add("增加源代码交付与部署文档清单");
            }
            if (lowered.contains("知识产权") || lowered.contains("代码")) {
                questions.add("明确知识产权归属与开源组件责任");
            }
        } else if (normalizedScene.equals("risk")) {
            questions.add("检查需求变更计费机制是否完整");
            questions.add("补充逾期交付的宽限期与违约责任");
        } else if (normalizedScene.equals("case")) {
            questions.add("补充与当前条款最接近的争议案例摘要");
            questions.add("对比近三年类似合同纠纷的裁判倾向");
        }

        return questions;
    }

    private RecommendationItem toRecommendationItem(
            String text,
            String scope,
            String scene,
            String roleName,
            String recentText
    ) {
        RecommendationItem item = new RecommendationItem();
        item.setText(text);
        item.setScope(scope);
        item.setTargetAction(resolveTargetAction(scope));
        item.setConfidence(calculateConfidence(text, scene, recentText));
        item.setReason(buildReason(scope, scene, roleName, recentText));
        return item;
    }

    private String normalizeScope(String scope) {
        if (scope == null || scope.isBlank()) {
            return "chat";
        }
        String normalized = scope.trim().toLowerCase(Locale.ROOT);
        return switch (normalized) {
            case "rag", "workbench", "chat" -> normalized;
            default -> "chat";
        };
    }

    private String resolveTargetAction(String scope) {
        return switch (scope) {
            case "rag" -> "fill_query";
            case "workbench" -> "fill_input";
            default -> "fill_input";
        };
    }

    private double calculateConfidence(String text, String scene, String recentText) {
        double confidence = 0.72;
        if (scene != null && !scene.isBlank()) {
            confidence += 0.08;
        }
        if (recentText != null && !recentText.isBlank() && recentText.contains("合同") && text.contains("合同")) {
            confidence += 0.07;
        }
        if (text.contains("验收") || text.contains("知识产权") || text.contains("学习")) {
            confidence += 0.05;
        }
        return Math.min(confidence, 0.96);
    }

    private String buildReason(String scope, String scene, String roleName, String recentText) {
        StringBuilder builder = new StringBuilder();
        builder.append("基于");
        builder.append(resolveScopeLabel(scope));
        builder.append("场景");
        if (roleName != null && !roleName.isBlank()) {
            builder.append("与").append(roleName).append("角色");
        }
        if (scene != null && !scene.isBlank()) {
            builder.append("，聚焦").append(scene).append("标签");
        }
        if (recentText != null && !recentText.isBlank()) {
            builder.append("的当前上下文生成");
        }
        return builder.toString();
    }

    private String resolveScopeLabel(String scope) {
        return switch (scope) {
            case "rag" -> "知识检索";
            case "workbench" -> "工作台";
            default -> "对话";
        };
    }

    /**
     * 获取默认推荐问题
     */
    private List<String> getDefaultRecommendations() {
        return List.of("能详细解释一下吗？", "有什么建议吗？", "还有其他相关问题吗？");
    }
}
