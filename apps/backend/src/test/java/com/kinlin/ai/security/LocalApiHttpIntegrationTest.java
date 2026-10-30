package com.kinlin.ai.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.test.context.ActiveProfiles;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/** Real loopback HTTP through the embedded server, without Vite or a separate gateway. */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@ActiveProfiles("test")
class LocalApiHttpIntegrationTest {
    @LocalServerPort
    private int port;

    @Autowired
    private ObjectMapper mapper;

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
        assertThat(send(request("/api/auth/logout").header("Authorization", "Bearer " + token)
                .POST(HttpRequest.BodyPublishers.noBody())).statusCode()).isEqualTo(204);
        assertThat(send(request("/api/users/me").header("Authorization", "Bearer " + token).GET())
                .statusCode()).isEqualTo(401);
        assertThat(send(request("/api/agentos/v2/missions").GET()).statusCode()).isEqualTo(401);
    }
}
