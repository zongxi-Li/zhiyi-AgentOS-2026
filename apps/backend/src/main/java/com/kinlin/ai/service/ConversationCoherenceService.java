package com.kinlin.ai.service;

import com.kinlin.ai.entity.Message;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 对话连贯性检查服务
 */
@Slf4j
@Service
public class ConversationCoherenceService {

    /**
     * 检查对话连贯性
     */
    public CoherenceResult checkCoherence(List<Message> messages) {
        if (messages.size() < 2) {
            return new CoherenceResult(true, "对话消息不足，无法检查连贯性");
        }

        int issues = 0;
        StringBuilder issuesList = new StringBuilder();

        for (int i = 1; i < messages.size(); i++) {
            Message prev = messages.get(i - 1);
            Message curr = messages.get(i);

            // 检查是否连续出现相同角色的消息
            if (prev.getRole() == curr.getRole()) {
                issues++;
                issuesList.append("第").append(i).append("条消息角色重复; ");
            }

            // 检查消息是否为空
            if (curr.getContent() == null || curr.getContent().trim().isEmpty()) {
                issues++;
                issuesList.append("第").append(i).append("条消息内容为空; ");
            }

            // 检查消息长度是否异常
            if (curr.getContent() != null && curr.getContent().length() > 10000) {
                issues++;
                issuesList.append("第").append(i).append("条消息过长; ");
            }
        }

        boolean isCoherent = issues == 0;
        String message = isCoherent 
                ? "对话连贯性良好" 
                : "发现 " + issues + " 个连贯性问题: " + issuesList.toString();

        return new CoherenceResult(isCoherent, message);
    }

    /**
     * 连贯性检查结果
     */
    public record CoherenceResult(boolean isCoherent, String message) {
    }
}

