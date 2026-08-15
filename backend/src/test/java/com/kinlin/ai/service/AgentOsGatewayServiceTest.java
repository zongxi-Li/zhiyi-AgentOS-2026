package com.kinlin.ai.service;

import com.kinlin.ai.config.AgentProperties;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.web.reactive.function.client.ClientResponse;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;

class AgentOsGatewayServiceTest {

    @Test
    void preservesSuccessfulUpstreamStatusAndReferenceProjection() {
        AgentOsGatewayService service = service(HttpStatus.ACCEPTED,
                "{\"runId\":\"run_1\",\"executionState\":{\"outputRefs\":{}}}");

        Map<String, Object> result = service.post("/ai/agentos/v2/runs", Map.of("title", "review"));

        assertEquals(202, result.get(AgentOsGatewayService.INTERNAL_HTTP_STATUS_KEY));
        assertEquals("run_1", result.get("runId"));
    }

    @Test
    void preservesClientStatusButDoesNotRelaySensitiveErrorFields() {
        AgentOsGatewayService service = service(HttpStatus.CONFLICT,
                "{\"detail\":\"clientRequestId conflict\",\"prompt\":\"PRIVATE\",\"arguments\":{\"secret\":\"x\"}}");

        Map<String, Object> result = service.post("/ai/agentos/v2/runs", Map.of());

        assertEquals(409, result.get(AgentOsGatewayService.INTERNAL_HTTP_STATUS_KEY));
        assertEquals("clientRequestId conflict", result.get("message"));
        assertFalse(result.toString().contains("PRIVATE"));
        assertFalse(result.toString().contains("secret"));
    }

    @Test
    void mapsServerErrorsToOpaqueBadGatewayResponses() {
        AgentOsGatewayService service = service(HttpStatus.INTERNAL_SERVER_ERROR,
                "{\"detail\":\"PRIVATE MODEL RESPONSE\"}");

        Map<String, Object> result = service.get("/ai/agentos/v2/runs/run_1");

        assertEquals(502, result.get(AgentOsGatewayService.INTERNAL_HTTP_STATUS_KEY));
        assertEquals("AGENTOS_UPSTREAM_ERROR", result.get("error"));
        assertFalse(result.toString().contains("PRIVATE"));
    }

    private AgentOsGatewayService service(HttpStatus status, String body) {
        AgentProperties properties = new AgentProperties();
        properties.setEnabled(true);
        properties.setTimeoutMs(5_000);
        WebClient.Builder builder = WebClient.builder().exchangeFunction(request -> Mono.just(
                ClientResponse.create(status)
                        .header(HttpHeaders.CONTENT_TYPE, MediaType.APPLICATION_JSON_VALUE)
                        .body(body)
                        .build()
        ));
        return new AgentOsGatewayService(builder, properties, "http://agentos");
    }
}
