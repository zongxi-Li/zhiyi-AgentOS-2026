package com.kinlin.ai.infrastructure.http;

import com.kinlin.ai.client.DigitalHumanClient;
import com.kinlin.ai.client.PlatformAiClientException;
import com.kinlin.ai.dto.DigitalHumanRequest;
import com.kinlin.ai.dto.DigitalHumanResponse;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.client.MultipartBodyBuilder;
import org.springframework.stereotype.Component;

import java.util.HashMap;
import java.util.Map;
import java.util.function.Supplier;

/**
 * WebClient implementation of the digital-human capability
 * ({@code /ai/digital-human/**} family), including the frozen error semantics:
 * upstream 404 on {@link #get} maps to the "数字人不存在" response, other upstream
 * statuses keep the "AI服务返回错误: <status>" wording of the former onStatus
 * branch, and timeout / connection failures keep their existing texts.
 */
@Component
public class WebClientDigitalHumanClient implements DigitalHumanClient {

    private final PlatformAiTransport transport;

    public WebClientDigitalHumanClient(PlatformAiTransport transport) {
        this.transport = transport;
    }

    @Override
    public DigitalHumanResponse create(DigitalHumanRequest request) {
        Map<String, Object> requestBody = new HashMap<>();
        requestBody.put("role_id", request.getRoleId());
        if (request.getPersonality() != null) {
            requestBody.put("personality", request.getPersonality());
        }
        if (request.getProfession() != null) {
            requestBody.put("profession", request.getProfession());
        }
        requestBody.put("style", request.getStyle() != null ? request.getStyle() : "realistic");

        return call(() -> transport.postJson("/ai/digital-human/create", requestBody, TransportTypes.MAP));
    }

    @Override
    public DigitalHumanResponse updateAnimation(String roleId, byte[] audioData, String text) {
        MultipartBodyBuilder builder = new MultipartBodyBuilder();
        builder.part("role_id", roleId);
        builder.part("text", text);
        builder.part("audio", audioData)
                .filename("audio.wav")
                .contentType(MediaType.APPLICATION_OCTET_STREAM);

        return call(() -> transport.postMultipart(
                "/ai/digital-human/animation", builder.build(), TransportTypes.MAP));
    }

    @Override
    public DigitalHumanResponse get(String roleId) {
        try {
            return assemble(transport.get("/ai/digital-human/{roleId}", TransportTypes.MAP, roleId));
        } catch (PlatformAiClientException error) {
            if (error.type() == PlatformAiClientException.Type.REJECTED && error.upstreamStatus() == 404) {
                return assemble(notFoundResponse(roleId));
            }
            return assemble(errorResponseMap(error));
        }
    }

    @Override
    public DigitalHumanResponse switchStyle(String roleId, String newStyle) {
        Map<String, Object> requestBody = new HashMap<>();
        requestBody.put("role_id", roleId);
        requestBody.put("new_style", newStyle);

        return call(() -> transport.postJson("/ai/digital-human/style", requestBody, TransportTypes.MAP));
    }

    private DigitalHumanResponse call(Supplier<Map<String, Object>> call) {
        try {
            return assemble(call.get());
        } catch (PlatformAiClientException error) {
            return assemble(errorResponseMap(error));
        }
    }

    private static Map<String, Object> notFoundResponse(String roleId) {
        Map<String, Object> notFoundMap = new HashMap<>();
        notFoundMap.put("success", false);
        notFoundMap.put("error", "数字人不存在: " + roleId);
        notFoundMap.put("message", "数字人不存在: " + roleId);
        return notFoundMap;
    }

    /**
     * Status-derived failures reproduce the frozen onStatus wording
     * ("AI服务返回错误: 503 SERVICE_UNAVAILABLE"); reactor/netty failures keep the
     * raw failure text with the former null-message fallbacks.
     */
    private static Map<String, Object> errorResponseMap(PlatformAiClientException error) {
        String errorMessage;
        if (error.type() == PlatformAiClientException.Type.REJECTED
                || error.type() == PlatformAiClientException.Type.UPSTREAM_ERROR) {
            errorMessage = "AI服务返回错误: " + upstreamStatusText(error);
        } else {
            errorMessage = error.getMessage();
            if (errorMessage == null || errorMessage.isEmpty()) {
                errorMessage = switch (error.type()) {
                    case TIMEOUT -> "请求超时，请稍后重试";
                    case UNAVAILABLE -> "无法连接到AI服务，请稍后重试";
                    default -> "调用AI服务失败";
                };
            }
        }
        Map<String, Object> errorMap = new HashMap<>();
        errorMap.put("success", false);
        errorMap.put("error", errorMessage);
        errorMap.put("message", errorMessage);
        return errorMap;
    }

    /** Matches the former {@code clientResponse.statusCode()} rendering (e.g. "503 SERVICE_UNAVAILABLE"). */
    private static String upstreamStatusText(PlatformAiClientException error) {
        try {
            return HttpStatus.valueOf(error.upstreamStatus()).toString();
        } catch (IllegalArgumentException nonStandardStatus) {
            return String.valueOf(error.upstreamStatus());
        }
    }

    private static DigitalHumanResponse assemble(Map<String, Object> responseMap) {
        DigitalHumanResponse response = new DigitalHumanResponse();
        if (responseMap != null) {
            Boolean success = (Boolean) responseMap.get("success");
            if (success != null) {
                response.setSuccess(success);
            } else if (responseMap.containsKey("error")) {
                response.setSuccess(false);
                response.setMessage((String) responseMap.get("error"));
            } else {
                response.setSuccess(true);
            }
            Map<String, Object> data = dataOf(responseMap);
            response.setData(data);
            response.setMessage((String) responseMap.get("message"));
        } else {
            response.setSuccess(false);
            response.setMessage("AI服务无响应");
        }
        return response;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> dataOf(Map<String, Object> responseMap) {
        return (Map<String, Object>) responseMap.get("data");
    }
}
