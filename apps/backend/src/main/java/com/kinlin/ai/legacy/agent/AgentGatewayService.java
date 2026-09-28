package com.kinlin.ai.legacy.agent;

import com.kinlin.ai.config.AgentProperties;
import com.kinlin.ai.dto.agent.AgentChatRequest;
import com.kinlin.ai.dto.agent.AgentChatResponse;
import com.kinlin.ai.gateway.PythonServiceAuthentication;
import com.kinlin.ai.gateway.TrustedUserContextForwarder;
import io.micrometer.core.instrument.MeterRegistry;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.ClientHttpResponse;
import org.springframework.stereotype.Service;
import org.springframework.web.client.HttpStatusCodeException;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestTemplate;

import java.time.Duration;

/**
 * LEGACY_AI gateway for forwarding lawyer-agent requests to Python service.
 *
 * <p>Isolated into {@code com.kinlin.ai.legacy.agent} in J1.1. The RestTemplate
 * transport is intentionally NOT migrated to WebClient: this path is a legacy
 * deprecation candidate (J1.3) and must stay behavior-identical until then.
 * Removal of this class and the {@code agent.python.*-chat-url} configuration
 * family is owned by J1.3.</p>
 */
@Slf4j
@Service
public class AgentGatewayService {

    private final AgentProperties agentProperties;
    private final RestTemplate restTemplate;
    private final MeterRegistry meterRegistry;

    public AgentGatewayService(
            RestTemplateBuilder restTemplateBuilder,
            AgentProperties agentProperties,
            PythonServiceAuthentication authentication,
            TrustedUserContextForwarder userContextForwarder,
            MeterRegistry meterRegistry
    ) {
        this.agentProperties = agentProperties;
        this.meterRegistry = meterRegistry;
        this.restTemplate = restTemplateBuilder
                .setConnectTimeout(Duration.ofMillis(agentProperties.getTimeoutMs()))
                .setReadTimeout(Duration.ofMillis(agentProperties.getTimeoutMs()))
                .additionalInterceptors((request, body, execution) -> {
                    authentication.apply(request.getHeaders());
                    userContextForwarder.apply(request.getHeaders());
                    long start = System.nanoTime();
                    try {
                        ClientHttpResponse response = execution.execute(request, body);
                        meterRegistry.counter("kinlin.python.outbound.requests",
                                        "family", "legacy_agent", "outcome", "response",
                                        "status", String.valueOf(response.getStatusCode().value()))
                                .increment();
                        meterRegistry.timer("kinlin.python.outbound.duration",
                                        "family", "legacy_agent", "outcome", "response")
                                .record(System.nanoTime() - start, java.util.concurrent.TimeUnit.NANOSECONDS);
                        return response;
                    } catch (Exception error) {
                        String outcome = error instanceof ResourceAccessException ? "connection_error" : "error";
                        meterRegistry.counter("kinlin.python.outbound.requests",
                                        "family", "legacy_agent", "outcome", outcome, "status", "none")
                                .increment();
                        throw error;
                    }
                })
                .build();
    }

    public AgentChatResponse chatWithLawyerAgent(AgentChatRequest request) {
        return chatWithAgent(
                request,
                agentProperties.getPython().getLawyerChatUrl(),
                "lawyer"
        );
    }

    public AgentChatResponse chatWithTeacherAgent(AgentChatRequest request) {
        return chatWithAgent(
                request,
                agentProperties.getPython().getTeacherChatUrl(),
                "teacher"
        );
    }

    public AgentChatResponse chatWithProgrammerAgent(AgentChatRequest request) {
        return chatWithAgent(
                request,
                agentProperties.getPython().getProgrammerChatUrl(),
                "programmer"
        );
    }

    public AgentChatResponse chatWithWriterAgent(AgentChatRequest request) {
        return chatWithAgent(
                request,
                agentProperties.getPython().getWriterChatUrl(),
                "writer"
        );
    }

    private AgentChatResponse chatWithAgent(AgentChatRequest request, String endpointUrl, String roleLabel) {
        if (!agentProperties.isEnabled()) {
            return AgentChatResponse.failure(
                    request.getSessionId(),
                    "Agent service is disabled by configuration.",
                    "agent.disabled"
            );
        }

        try {
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            HttpEntity<AgentChatRequest> httpEntity = new HttpEntity<>(request, headers);

            ResponseEntity<AgentChatResponse> response = restTemplate.postForEntity(
                    endpointUrl,
                    httpEntity,
                    AgentChatResponse.class
            );

            if (response.getBody() == null) {
                return AgentChatResponse.failure(
                        request.getSessionId(),
                        "Python agent returned empty response.",
                        "agent.empty_response"
                );
            }

            AgentChatResponse body = response.getBody();
            if (body.getSessionId() == null || body.getSessionId().isBlank()) {
                body.setSessionId(request.getSessionId());
            }
            return body;
        } catch (ResourceAccessException e) {
            log.error("Python agent access timeout/error", e);
            return AgentChatResponse.failure(
                    request.getSessionId(),
                    "Python agent timeout or unreachable. Please try again later.",
                    e.getMessage()
            );
        } catch (HttpStatusCodeException e) {
            log.error("Python agent HTTP error: {}", e.getStatusCode(), e);
            return AgentChatResponse.failure(
                    request.getSessionId(),
                    "Python agent returned an error status.",
                    e.getResponseBodyAsString()
            );
        } catch (Exception e) {
            log.error("Unexpected agent gateway error", e);
            return AgentChatResponse.failure(
                    request.getSessionId(),
                    "Unexpected error while calling " + roleLabel + " agent.",
                    e.getMessage()
            );
        }
    }
}
