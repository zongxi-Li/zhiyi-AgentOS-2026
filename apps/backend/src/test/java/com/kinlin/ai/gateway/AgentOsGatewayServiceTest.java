package com.kinlin.ai.gateway;

import com.kinlin.ai.client.AgentOsClient;
import com.kinlin.ai.config.AgentProperties;
import com.kinlin.ai.dto.agentos.AgentOsMissionResponse;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.web.reactive.function.client.ClientResponse;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.time.Duration;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;

class AgentOsGatewayServiceTest {

    @Test
    void preservesSuccessfulUpstreamStatusAndReferenceProjection() {
        AgentOsGatewayService service = service(HttpStatus.ACCEPTED,
                "{\"runId\":\"run_1\",\"executionState\":{\"outputRefs\":{}}}");

        Map<String, Object> result = service.post("/ai/agentos/v2/runs", Map.of("title", "review"));

        assertEquals(202, result.get(AgentOsClient.INTERNAL_HTTP_STATUS_KEY));
        assertEquals("run_1", result.get("runId"));
    }

    @Test
    void preservesClientStatusButDoesNotRelaySensitiveErrorFields() {
        AgentOsGatewayService service = service(HttpStatus.CONFLICT,
                "{\"code\":\"AGENTOS_CONFLICT\",\"message\":\"clientRequestId conflict\","
                        + "\"requestId\":\"trace-1\",\"prompt\":\"PRIVATE\","
                        + "\"arguments\":{\"secret\":\"x\"}}");

        Map<String, Object> result = service.post("/ai/agentos/v2/runs", Map.of());

        assertEquals(409, result.get(AgentOsClient.INTERNAL_HTTP_STATUS_KEY));
        assertEquals("AGENTOS_CONFLICT", result.get("code"));
        assertEquals("clientRequestId conflict", result.get("message"));
        assertEquals("trace-1", result.get("requestId"));
        assertFalse(result.toString().contains("PRIVATE"));
        assertFalse(result.toString().contains("secret"));
    }

    @Test
    void mapsServerErrorsToOpaqueBadGatewayResponses() {
        AgentOsGatewayService service = service(HttpStatus.INTERNAL_SERVER_ERROR,
                "{\"detail\":\"PRIVATE MODEL RESPONSE\"}");

        Map<String, Object> result = service.get("/ai/agentos/v2/runs/run_1");

        assertEquals(502, result.get(AgentOsClient.INTERNAL_HTTP_STATUS_KEY));
        assertEquals("AGENTOS_UPSTREAM_ERROR", result.get("code"));
        assertFalse(result.toString().contains("PRIVATE"));
    }

    @Test
    void boundsReadProjectionWaitsWithTheProgressTimeout() {
        AgentProperties properties = new AgentProperties();
        properties.setEnabled(true);
        properties.setTimeoutMs(5_000);
        properties.setProgressTimeoutMs(10);
        WebClient.Builder builder = WebClient.builder().exchangeFunction(request -> Mono.never());
        AgentOsGatewayService service = new AgentOsGatewayService(builder.clone().baseUrl("http://agentos").build(), properties);

        Map<String, Object> result = service.get("/ai/agentos/v2/runs");

        assertEquals(503, result.get(AgentOsClient.INTERNAL_HTTP_STATUS_KEY));
        assertEquals("AGENTOS_UPSTREAM_UNAVAILABLE", result.get("code"));
    }

    @Test
    void typedSuccessFailsClosedWhenUpstreamContractIsMalformed() {
        AgentOsGatewayService service = service(HttpStatus.ACCEPTED,
                "{\"runId\":\"run_1\",\"executionState\":{\"secret\":\"PRIVATE\"}}");

        AgentOsClient.TypedResponse<AgentOsMissionResponse> result = service.postTyped(
                "/ai/agentos/v2/missions", Map.of("title", "review"), AgentOsMissionResponse.class
        );

        assertEquals(502, result.status());
        assertEquals("AGENTOS_CONTRACT_INVALID", result.error().code());
        assertFalse(result.error().toString().contains("PRIVATE"));
    }

    @Test
    void givesMissionListTheRegularAgentTimeout() {
        AgentProperties properties = new AgentProperties();
        properties.setEnabled(true);
        properties.setTimeoutMs(500);
        properties.setProgressTimeoutMs(10);
        WebClient.Builder builder = WebClient.builder().exchangeFunction(request ->
                Mono.delay(Duration.ofMillis(50)).map(ignore -> ClientResponse.create(HttpStatus.OK)
                        .header(HttpHeaders.CONTENT_TYPE, MediaType.APPLICATION_JSON_VALUE)
                        .body("{\"items\":[]}")
                        .build())
        );
        AgentOsGatewayService service = new AgentOsGatewayService(builder.clone().baseUrl("http://agentos").build(), properties);

        Map<String, Object> result = service.get("/ai/agentos/v2/missions?page=1&pageSize=100");

        assertEquals(200, result.get(AgentOsClient.INTERNAL_HTTP_STATUS_KEY));
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
        return new AgentOsGatewayService(builder.clone().baseUrl("http://agentos").build(), properties);
    }
}
