package com.kinlin.ai.service;

import com.kinlin.ai.client.DigitalHumanClient;
import com.kinlin.ai.dto.DigitalHumanRequest;
import com.kinlin.ai.dto.DigitalHumanResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

/**
 * 数字人应用服务：数字人能力的业务编排与 fallback 决策。
 *
 * <p>HTTP 细节、multipart 组包与 transport 错误语义映射已下沉到
 * {@link DigitalHumanClient}；本层保留请求校验与既有的兜底错误响应。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class DigitalHumanService {

    private final DigitalHumanClient digitalHumanClient;

    /**
     * 创建数字人
     */
    public DigitalHumanResponse createDigitalHuman(DigitalHumanRequest request) {
        try {
            // 验证请求参数
            if (request == null || request.getRoleId() == null || request.getRoleId().trim().isEmpty()) {
                log.warn("创建数字人请求参数无效: roleId为空");
                DigitalHumanResponse errorResponse = new DigitalHumanResponse();
                errorResponse.setSuccess(false);
                errorResponse.setMessage("角色ID不能为空");
                return errorResponse;
            }

            log.info("调用Python服务创建数字人: roleId={}, style={}", request.getRoleId(), request.getStyle());
            return digitalHumanClient.create(request);
        } catch (Exception e) {
            log.error("创建数字人失败", e);
            return failure(e, "创建数字人失败，请检查AI服务是否运行");
        }
    }

    /**
     * 更新数字人动画
     */
    public DigitalHumanResponse updateAnimation(String roleId, byte[] audioData, String text) {
        try {
            return digitalHumanClient.updateAnimation(roleId, audioData, text);
        } catch (Exception e) {
            log.error("更新数字人动画失败", e);
            return failure(e, "更新数字人动画失败，请检查AI服务是否运行");
        }
    }

    /**
     * 获取数字人信息
     */
    public DigitalHumanResponse getDigitalHuman(String roleId) {
        try {
            return digitalHumanClient.get(roleId);
        } catch (Exception e) {
            log.error("获取数字人失败", e);
            return failure(e, "获取数字人失败，请检查AI服务是否运行");
        }
    }

    /**
     * 切换数字人风格
     */
    public DigitalHumanResponse switchStyle(String roleId, String newStyle) {
        try {
            return digitalHumanClient.switchStyle(roleId, newStyle);
        } catch (Exception e) {
            log.error("切换数字人风格失败", e);
            return failure(e, "切换数字人风格失败，请检查AI服务是否运行");
        }
    }

    private static DigitalHumanResponse failure(Exception e, String fallbackMessage) {
        DigitalHumanResponse response = new DigitalHumanResponse();
        response.setSuccess(false);
        String errorMessage = e.getMessage();
        if (errorMessage == null || errorMessage.isEmpty()) {
            errorMessage = fallbackMessage;
        }
        response.setMessage(errorMessage);
        return response;
    }
}
