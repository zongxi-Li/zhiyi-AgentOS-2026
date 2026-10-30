package com.kinlin.ai.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.kinlin.ai.gateway.AiProxyService;
import jakarta.servlet.http.HttpServletRequest;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.ResponseEntity;
import org.springframework.test.context.ActiveProfiles;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.times;

/** Real loopback HTTP through the embedded server, without Vite or a separate gateway. */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@ActiveProfiles("test")
class LocalApiHttpIntegrationTest {
    @LocalServerPort
    private int port;

    @Autowired
    private ObjectMapper mapper;

    @MockBean
    private AiProxyService aiProxy;

    private final HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(10)).build();

    private HttpRequest.Builder request(String path) {
        return HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + path))
                .timeout(Duration.ofSeconds(15)).header("Origin", "kinlin-app://shell");
    }

    private HttpResponse<String> send(HttpRequest.Builder request) throws Exception {
        return client.send(request.build(), HttpResponse.BodyHandlers.ofString());
    }

    @Test
    void desktopOriginCanRegisterLoginReadAndLogoutViaLocalApiAliases() throws Exception {
        var preflight = send(request("/api/auth/login")
                .header("Access-Control-Request-Method", "POST")
                .header("Access-Control-Request-Headers", "content-type")
                .method("OPTIONS", HttpRequest.BodyPublishers.noBody()));
        assertThat(preflight.statusCode()).isEqualTo(200);
        assertThat(preflight.headers().firstValue("Access-Control-Allow-Origin")).contains("kinlin-app://shell");

        String body = "{\"username\":\"local_" + UUID.randomUUID().toString().substring(0, 12)
                + "\",\"password\":\"pass-123456\"}";
        var registered = send(request("/api/auth/register").header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(body)));
        assertThat(registered.statusCode()).isEqualTo(200);
        var login = send(request("/api/auth/login").header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(body)));
        assertThat(login.statusCode()).isEqualTo(200);
        String token = mapper.readTree(login.body()).get("token").asText();
        assertThat(token).isNotBlank();
        var me = send(request("/api/users/me").header("Authorization", "Bearer " + token).GET());
        assertThat(me.statusCode()).isEqualTo(200);
        assertThat(me.headers().firstValue("Access-Control-Allow-Origin")).contains("kinlin-app://shell");
        // The approval/cancel clients share the /api Axios base. Both must reach
        // the authenticated /ai controller with their original JSON bodies.
        var forwarded = new java.util.ArrayList<String>();
        doAnswer(invocation -> {
            HttpServletRequest incoming = invocation.getArgument(0);
            forwarded.add(incoming.getRequestURI());
            var payload = mapper.readTree(incoming.getInputStream());
            if (incoming.getRequestURI().contains("/approvals/")) {
                assertThat(payload.get("decision").asText()).isEqualTo("deny");
                assertThat(payload.get("sessionId").asText()).isEqualTo("route-test");
            } else {
                assertThat(payload.get("requestId").asText()).isEqualTo("route-test");
            }
            return ResponseEntity.ok("{}".getBytes(java.nio.charset.StandardCharsets.UTF_8));
        }).when(aiProxy).forward(any(HttpServletRequest.class));
        for (String path : new String[]{"/api/ai/chat/approvals/route-test", "/api/ai/chat/text/cancel"}) {
            assertThat(send(request(path).header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString("{}"))).statusCode()).isEqualTo(401);
            String payload = path.contains("/approvals/")
                    ? "{\"decision\":\"deny\",\"sessionId\":\"route-test\"}"
                    : "{\"requestId\":\"route-test\"}";
            assertThat(send(request(path).header("Authorization", "Bearer " + token)
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(payload))).statusCode()).isEqualTo(200);
        }
        assertThat(forwarded).containsExactly("/ai/chat/approvals/route-test", "/ai/chat/text/cancel");
        verify(aiProxy, times(2)).forward(any(HttpServletRequest.class));
        assertThat(send(request("/api/auth/logout").header("Authorization", "Bearer " + token)
                .POST(HttpRequest.BodyPublishers.noBody())).statusCode()).isEqualTo(204);
        assertThat(send(request("/api/users/me").header("Authorization", "Bearer " + token).GET())
                .statusCode()).isEqualTo(401);
        assertThat(send(request("/api/agentos/v2/missions").GET()).statusCode()).isEqualTo(401);
    }
}
