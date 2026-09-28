package com.kinlin.ai.legacy.agent;

import com.kinlin.ai.config.AgentProperties;
import com.kinlin.ai.dto.agent.AgentChatRequest;
import com.kinlin.ai.dto.agent.AgentChatResponse;
import com.kinlin.ai.gateway.AiGatewayHeaders;
import com.kinlin.ai.gateway.PythonServiceAuthentication;
import com.kinlin.ai.gateway.TrustedUserContextForwarder;
import com.kinlin.ai.security.AuthenticatedUserContext;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Characterization tests for the LEGACY_AI role chat transport (J1.1).
 *
 * <p>These tests freeze the current behavior of the RestTemplate-based path so the
 * J1.3 cleanup can compare against them: endpoint resolution from
 * {@code agent.python.base-url}, header forwarding, and error mapping. They are
 * intentional records of legacy semantics — including the raw upstream error body
 * leak — not a statement of desired behavior.</p>
 */
class LegacyAgentGatewayServiceTest {

    private HttpServer server;
    private String baseUrl;
    private final AtomicReference<com.sun.net.httpserver.Headers> capturedHeaders = new AtomicReference<>();
    private final AtomicReference<String> capturedPath = new AtomicReference<>();

    @BeforeEach
    void startServer() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.setExecutor(Executors.newCachedThreadPool());
        server.createContext("/ai/agent/lawyer/chat", exchange -> {
            capturedHeaders.set(exchange.getRequestHeaders());
            capturedPath.set(exchange.getRequestURI().getPath());
            respond(exchange, 200, "{\"success\":true,\"answer\":\"legacy answer\",\"sessionId\":\"\"}");
        });
        server.start();
        baseUrl = "http://127.0.0.1:" + server.getAddress().getPort();
        UUID userId = UUID.randomUUID();
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(
                        new AuthenticatedUserContext(userId, userId.toString(), "USER", null, null),
                        null, List.of())
        );
    }

    @AfterEach
    void stopServer() {
        server.stop(0);
        SecurityContextHolder.clearContext();
    }

    @Test
    void forwardsToLegacyRoleEndpointResolvedFromLegacyBaseUrl() {
        AgentChatResponse response = service().chatWithLawyerAgent(request());

        assertTrue(response.isSuccess());
        assertEquals("legacy answer", response.getAnswer());
        assertEquals("/ai/agent/lawyer/chat", capturedPath.get());
    }

    @Test
    void forwardsInternalTokenAndRegeneratedIdentityHeaders() {
        service().chatWithLawyerAgent(request());

        assertEquals(INTERNAL_TOKEN,
                capturedHeaders.get().getFirst(AiGatewayHeaders.INTERNAL_SERVICE_TOKEN));
        UUID contextUserId = com.kinlin.ai.security.AuthenticatedUser.currentUserId().orElseThrow();
        assertEquals(contextUserId.toString(),
                capturedHeaders.get().getFirst(AiGatewayHeaders.AUTHENTICATED_USER_ID));
        assertEquals("USER", capturedHeaders.get().getFirst(AiGatewayHeaders.AUTHENTICATED_USER_ROLE));
    }

    @Test
    void fillsBlankUpstreamSessionIdFromRequest() {
        AgentChatResponse response = service().chatWithLawyerAgent(request());

        assertEquals("session-1", response.getSessionId());
    }

    @Test
    void mapsDisabledConfigurationToStableFailureCode() {
        AgentProperties properties = properties();
        properties.setEnabled(false);

        AgentChatResponse response = service(properties).chatWithLawyerAgent(request());

        assertFalse(response.isSuccess());
        assertEquals("agent.disabled", response.getError());
    }

    @Test
    void mapsUpstreamHttpErrorToFailureWithRawLegacyBody() throws IOException {
        server.createContext("/ai/agent/teacher/chat", exchange ->
                respond(exchange, 500, "{\"detail\":\"legacy private detail\"}"));

        AgentChatResponse response = service().chatWithTeacherAgent(request());

        assertFalse(response.isSuccess());
        assertEquals("Python agent returned an error status.", response.getMessage());
        assertTrue(response.getError().contains("legacy private detail"));
    }

    @Test
    void mapsConnectionFailureToTimeoutOrUnreachableFailure() {
        AgentProperties properties = properties();
        properties.getPython().setBaseUrl("http://127.0.0.1:1");

        AgentChatResponse response = service(properties).chatWithLawyerAgent(request());

        assertFalse(response.isSuccess());
        assertEquals("Python agent timeout or unreachable. Please try again later.", response.getMessage());
    }

    private AgentGatewayService service() {
        return service(properties());
    }

    private AgentGatewayService service(AgentProperties properties) {
        com.kinlin.ai.gateway.AiInternalServiceToken internalToken =
                new com.kinlin.ai.gateway.AiInternalServiceToken();
        internalToken.setToken(INTERNAL_TOKEN);
        return new AgentGatewayService(
                new RestTemplateBuilder(),
                properties,
                new PythonServiceAuthentication(internalToken),
                new TrustedUserContextForwarder(),
                new SimpleMeterRegistry()
        );
    }

    private AgentProperties properties() {
        AgentProperties properties = new AgentProperties();
        properties.setEnabled(true);
        properties.setTimeoutMs(2000);
        properties.getPython().setBaseUrl(baseUrl);
        return properties;
    }

    private AgentChatRequest request() {
        AgentChatRequest request = new AgentChatRequest();
        request.setText("probe");
        request.setSessionId("session-1");
        return request;
    }

    /** The {@code AiInternalServiceToken} credential used across these tests. */
    private static final String INTERNAL_TOKEN = "legacy-internal-service-token-0123456789abcdef";

    private void respond(HttpExchange exchange, int status, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(status, bytes.length);
        exchange.getResponseBody().write(bytes);
        exchange.close();
    }
}
