package com.kinlin.ai.service;

import com.kinlin.ai.dto.DigitalHumanRequest;
import com.kinlin.ai.dto.DigitalHumanResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.client.MultipartBodyBuilder;
import org.springframework.stereotype.Service;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.web.reactive.function.BodyInserters;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.time.Duration;
import java.util.HashMap;
import java.util.Map;

/**
 * 数字人服务
 * 负责与Python AI服务的数字人功能通信
 */
@Slf4j
@Service
public class DigitalHumanService {

    private final WebClient webClient;
    
    // 类型引用，用于避免类型安全警告
    private static final ParameterizedTypeReference<Map<String, Object>> MAP_TYPE_REF = 
        new ParameterizedTypeReference<Map<String, Object>>() {};

    @Value("${ai.service.url}")
    private String aiServiceUrl;

    @Value("${ai.service.timeout}")
    private int timeout;

    public DigitalHumanService(WebClient.Builder webClientBuilder, 
                               @Value("${ai.service.url}") String aiServiceUrl, 
                               @Value("${ai.service.timeout}") int timeout) {
        this.aiServiceUrl = aiServiceUrl;
        this.timeout = timeout;
        this.webClient = webClientBuilder
                .baseUrl(aiServiceUrl)
                .build();
    }

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

            Map<String, Object> requestBody = new HashMap<>();
            requestBody.put("role_id", request.getRoleId());
            if (request.getPersonality() != null) {
                requestBody.put("personality", request.getPersonality());
            }
            if (request.getProfession() != null) {
                requestBody.put("profession", request.getProfession());
            }
            requestBody.put("style", request.getStyle() != null ? request.getStyle() : "realistic");

            log.info("调用Python服务创建数字人: roleId={}, style={}", request.getRoleId(), request.getStyle());

            Map<String, Object> responseMap = webClient.post()
                    .uri("/ai/digital-human/create")
                    .bodyValue(requestBody)
                    .retrieve()
                    .onStatus(status -> status.is4xxClientError() || status.is5xxServerError(), 
                        clientResponse -> {
                            log.error("Python服务返回错误状态: {}", clientResponse.statusCode());
                            return Mono.error(new RuntimeException("Python服务返回错误: " + clientResponse.statusCode()));
                        })
                    .bodyToMono(MAP_TYPE_REF)
                    .timeout(Duration.ofMillis(timeout))
                    .onErrorResume(e -> {
                        log.error("调用Python服务失败", e);
                        return Mono.just(createErrorResponseMap(e));
                    })
                    .block();

            DigitalHumanResponse response = new DigitalHumanResponse();
            if (responseMap != null) {
                Boolean success = (Boolean) responseMap.get("success");
                if (success != null) {
                    response.setSuccess(success);
                } else {
                    // 如果响应中没有success字段，检查是否有error字段
                    if (responseMap.containsKey("error")) {
                        response.setSuccess(false);
                        response.setMessage((String) responseMap.get("error"));
                    } else {
                        response.setSuccess(true);
                    }
                }
                @SuppressWarnings("unchecked")
                Map<String, Object> data = (Map<String, Object>) responseMap.get("data");
                response.setData(data);
                response.setMessage((String) responseMap.get("message"));
            } else {
                response.setSuccess(false);
                response.setMessage("Python服务无响应");
            }
            return response;
        } catch (Exception e) {
            log.error("创建数字人失败", e);
            DigitalHumanResponse response = new DigitalHumanResponse();
            response.setSuccess(false);
            String errorMessage = e.getMessage();
            if (errorMessage == null || errorMessage.isEmpty()) {
                errorMessage = "创建数字人失败，请检查Python服务是否运行";
            }
            response.setMessage(errorMessage);
            return response;
        }
    }

    /**
     * 创建错误响应Map
     */
    private Map<String, Object> createErrorResponseMap(Throwable e) {
        Map<String, Object> errorMap = new HashMap<>();
        errorMap.put("success", false);
        String errorMessage = e.getMessage();
        if (errorMessage == null || errorMessage.isEmpty()) {
            if (e instanceof java.util.concurrent.TimeoutException) {
                errorMessage = "请求超时，请检查Python服务是否正常运行";
            } else if (e instanceof org.springframework.web.reactive.function.client.WebClientException) {
                errorMessage = "无法连接到Python服务，请确保服务已启动";
            } else {
                errorMessage = "调用Python服务失败";
            }
        }
        errorMap.put("error", errorMessage);
        errorMap.put("message", errorMessage);
        return errorMap;
    }

    /**
     * 更新数字人动画
     */
    public DigitalHumanResponse updateAnimation(String roleId, byte[] audioData, String text) {
        try {
            MultipartBodyBuilder builder = new MultipartBodyBuilder();
            builder.part("role_id", roleId);
            builder.part("text", text);
            builder.part("audio", audioData)
                   .filename("audio.wav")
                   .contentType(MediaType.APPLICATION_OCTET_STREAM);

            Map<String, Object> responseMap = webClient.post()
                    .uri("/ai/digital-human/animation")
                    .contentType(MediaType.MULTIPART_FORM_DATA)
                    .body(BodyInserters.fromMultipartData(builder.build()))
                    .retrieve()
                    .onStatus(status -> status.is4xxClientError() || status.is5xxServerError(), 
                        clientResponse -> {
                            log.error("Python服务返回错误状态: {}", clientResponse.statusCode());
                            return Mono.error(new RuntimeException("Python服务返回错误: " + clientResponse.statusCode()));
                        })
                    .bodyToMono(MAP_TYPE_REF)
                    .timeout(Duration.ofMillis(timeout))
                    .onErrorResume(e -> {
                        log.error("调用Python服务失败", e);
                        return Mono.just(createErrorResponseMap(e));
                    })
                    .block();

            DigitalHumanResponse response = new DigitalHumanResponse();
            if (responseMap != null) {
                Boolean success = (Boolean) responseMap.get("success");
                if (success != null) {
                    response.setSuccess(success);
                } else {
                    response.setSuccess(false);
                    response.setMessage("Python服务响应格式错误");
                }
                @SuppressWarnings("unchecked")
                Map<String, Object> data = (Map<String, Object>) responseMap.get("data");
                response.setData(data);
                response.setMessage((String) responseMap.get("message"));
            } else {
                response.setSuccess(false);
                response.setMessage("Python服务无响应");
            }
            return response;
        } catch (Exception e) {
            log.error("更新数字人动画失败", e);
            DigitalHumanResponse response = new DigitalHumanResponse();
            response.setSuccess(false);
            String errorMessage = e.getMessage();
            if (errorMessage == null || errorMessage.isEmpty()) {
                errorMessage = "更新数字人动画失败，请检查Python服务是否运行";
            }
            response.setMessage(errorMessage);
            return response;
        }
    }

    /**
     * 获取数字人信息
     */
    public DigitalHumanResponse getDigitalHuman(String roleId) {
        try {
            Map<String, Object> requestBody = new HashMap<>();
            requestBody.put("role_id", roleId);

            Map<String, Object> responseMap = webClient.get()
                    .uri("/ai/digital-human/{roleId}", roleId)
                    .retrieve()
                    .onStatus(status -> status.is4xxClientError() || status.is5xxServerError(), 
                        clientResponse -> {
                            if (clientResponse.statusCode().value() == 404) {
                                log.info("数字人不存在: {}", roleId);
                                // 创建一个包含404信息的异常，在onErrorResume中处理
                                return Mono.error(new RuntimeException("NOT_FOUND:" + roleId));
                            }
                            log.error("Python服务返回错误状态: {}", clientResponse.statusCode());
                            return Mono.error(new RuntimeException("Python服务返回错误: " + clientResponse.statusCode()));
                        })
                    .bodyToMono(MAP_TYPE_REF)
                    .timeout(Duration.ofMillis(timeout))
                    .onErrorResume(e -> {
                        // 检查是否是404错误
                        if (e.getMessage() != null && e.getMessage().startsWith("NOT_FOUND:")) {
                            String notFoundRoleId = e.getMessage().substring("NOT_FOUND:".length());
                            log.info("数字人不存在，返回404响应: {}", notFoundRoleId);
                            return Mono.just(createNotFoundResponseMap(notFoundRoleId));
                        }
                        log.error("调用Python服务失败", e);
                        return Mono.just(createErrorResponseMap(e));
                    })
                    .block();

            DigitalHumanResponse response = new DigitalHumanResponse();
            if (responseMap != null) {
                Boolean success = (Boolean) responseMap.get("success");
                if (success != null) {
                    response.setSuccess(success);
                } else {
                    response.setSuccess(false);
                    response.setMessage("Python服务响应格式错误");
                }
                @SuppressWarnings("unchecked")
                Map<String, Object> data = (Map<String, Object>) responseMap.get("data");
                response.setData(data);
                response.setMessage((String) responseMap.get("message"));
            } else {
                response.setSuccess(false);
                response.setMessage("Python服务无响应");
            }
            return response;
        } catch (Exception e) {
            log.error("获取数字人失败", e);
            DigitalHumanResponse response = new DigitalHumanResponse();
            response.setSuccess(false);
            String errorMessage = e.getMessage();
            if (errorMessage == null || errorMessage.isEmpty()) {
                errorMessage = "获取数字人失败，请检查Python服务是否运行";
            }
            response.setMessage(errorMessage);
            return response;
        }
    }

    /**
     * 创建404响应Map
     */
    private Map<String, Object> createNotFoundResponseMap(String roleId) {
        Map<String, Object> notFoundMap = new HashMap<>();
        notFoundMap.put("success", false);
        notFoundMap.put("error", "数字人不存在: " + roleId);
        notFoundMap.put("message", "数字人不存在: " + roleId);
        return notFoundMap;
    }

    /**
     * 切换数字人风格
     */
    public DigitalHumanResponse switchStyle(String roleId, String newStyle) {
        try {
            Map<String, Object> requestBody = new HashMap<>();
            requestBody.put("role_id", roleId);
            requestBody.put("new_style", newStyle);

            Map<String, Object> responseMap = webClient.post()
                    .uri("/ai/digital-human/style")
                    .bodyValue(requestBody)
                    .retrieve()
                    .onStatus(status -> status.is4xxClientError() || status.is5xxServerError(), 
                        clientResponse -> {
                            log.error("Python服务返回错误状态: {}", clientResponse.statusCode());
                            return Mono.error(new RuntimeException("Python服务返回错误: " + clientResponse.statusCode()));
                        })
                    .bodyToMono(MAP_TYPE_REF)
                    .timeout(Duration.ofMillis(timeout))
                    .onErrorResume(e -> {
                        log.error("调用Python服务失败", e);
                        return Mono.just(createErrorResponseMap(e));
                    })
                    .block();

            DigitalHumanResponse response = new DigitalHumanResponse();
            if (responseMap != null) {
                Boolean success = (Boolean) responseMap.get("success");
                if (success != null) {
                    response.setSuccess(success);
                } else {
                    response.setSuccess(false);
                    response.setMessage("Python服务响应格式错误");
                }
                @SuppressWarnings("unchecked")
                Map<String, Object> data = (Map<String, Object>) responseMap.get("data");
                response.setData(data);
                response.setMessage((String) responseMap.get("message"));
            } else {
                response.setSuccess(false);
                response.setMessage("Python服务无响应");
            }
            return response;
        } catch (Exception e) {
            log.error("切换数字人风格失败", e);
            DigitalHumanResponse response = new DigitalHumanResponse();
            response.setSuccess(false);
            String errorMessage = e.getMessage();
            if (errorMessage == null || errorMessage.isEmpty()) {
                errorMessage = "切换数字人风格失败，请检查Python服务是否运行";
            }
            response.setMessage(errorMessage);
            return response;
        }
    }
}

