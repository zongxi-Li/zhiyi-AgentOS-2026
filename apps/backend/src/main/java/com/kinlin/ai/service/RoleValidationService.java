package com.kinlin.ai.service;

import com.kinlin.ai.entity.Role;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;

/**
 * 角色验证服务
 * 验证角色配置的合法性
 */
@Slf4j
@Service
public class RoleValidationService {

    /**
     * 验证角色配置
     */
    public ValidationResult validateRole(Role role) {
        List<String> errors = new ArrayList<>();

        // 验证名称
        if (role.getName() == null || role.getName().trim().isEmpty()) {
            errors.add("角色名称不能为空");
        } else if (role.getName().length() > 100) {
            errors.add("角色名称不能超过100个字符");
        }

        // 验证系统提示词
        if (role.getSystemPrompt() == null || role.getSystemPrompt().trim().isEmpty()) {
            errors.add("系统提示词不能为空");
        } else if (role.getSystemPrompt().length() > 2000) {
            errors.add("系统提示词不能超过2000个字符");
        }

        // 验证描述
        if (role.getDescription() != null && role.getDescription().length() > 500) {
            errors.add("角色描述不能超过500个字符");
        }

        // 验证对话风格
        if (role.getDialogueStyle() != null) {
            validateDialogueStyle(role.getDialogueStyle(), errors);
        }

        // 验证性格特点
        if (role.getPersonality() != null) {
            validatePersonality(role.getPersonality(), errors);
        }

        return new ValidationResult(errors.isEmpty(), errors);
    }

    private void validateDialogueStyle(java.util.Map<String, Object> style, List<String> errors) {
        // 验证正式度
        Object formality = style.get("formality");
        if (formality != null) {
            try {
                double value = Double.parseDouble(formality.toString());
                if (value < 0 || value > 1) {
                    errors.add("正式度必须在0-1之间");
                }
            } catch (NumberFormatException e) {
                errors.add("正式度必须是数字");
            }
        }

        // 验证温度
        Object warmth = style.get("warmth");
        if (warmth != null) {
            try {
                double value = Double.parseDouble(warmth.toString());
                if (value < 0 || value > 1) {
                    errors.add("温度必须在0-1之间");
                }
            } catch (NumberFormatException e) {
                errors.add("温度必须是数字");
            }
        }
    }

    private void validatePersonality(java.util.Map<String, Object> personality, List<String> errors) {
        // 性格特点验证（可以根据需要扩展）
        if (personality.size() > 20) {
            errors.add("性格特点不能超过20个");
        }
    }

    /**
     * 验证结果
     */
    public record ValidationResult(boolean valid, List<String> errors) {
    }
}

