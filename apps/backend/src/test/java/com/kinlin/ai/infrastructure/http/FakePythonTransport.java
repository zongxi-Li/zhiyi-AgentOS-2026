package com.kinlin.ai.infrastructure.http;

import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ReactiveHttpOutputMessage;
import org.springframework.http.client.reactive.ClientHttpRequest;
import org.springframework.http.codec.HttpMessageWriter;
import org.springframework.mock.http.client.reactive.MockClientHttpRequest;
import org.springframework.web.reactive.function.BodyInserter;
import org.springframework.web.reactive.function.client.ClientRequest;
import org.springframework.web.reactive.function.client.ClientResponse;
import org.springframework.web.reactive.function.client.ExchangeFunction;
import org.springframework.web.reactive.function.client.ExchangeStrategies;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.net.URI;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * Test transport for the platform-AI client implementations: a real WebClient
 * (actual serialization/URI building/codecs) whose exchange function records the
 * outgoing request and replays a canned upstream response.
 */
final class FakePythonTransport {

    private ClientRequest lastRequest;
    private String lastBodyJson;
    private HttpStatus nextStatus = HttpStatus.OK;
    private String nextBody = "{}";
    private Mono<ClientResponse> nextReaction;

    private final ExchangeFunction exchange = request -> {
        lastRequest = request;
        lastBodyJson = extractBody(request);
        if (nextReaction != null) {
            return nextReaction;
        }
        return Mono.just(ClientResponse.create(nextStatus)
                .header(HttpHeaders.CONTENT_TYPE, MediaType.APPLICATION_JSON_VALUE)
                .body(nextBody)
                .build());
    };

    WebClient client(String baseUrl) {
        return WebClient.builder().baseUrl(baseUrl).exchangeFunction(exchange).build();
    }

    void willReturn(int status, String body) {
        this.nextReaction = null;
        this.nextStatus = HttpStatus.valueOf(status);
        this.nextBody = body;
    }

    void willHang() {
        this.nextReaction = Mono.never();
    }

    void willFailWith(Throwable failure) {
        this.nextReaction = Mono.error(failure);
    }

    ClientRequest lastRequest() {
        if (lastRequest == null) {
            throw new IllegalStateException("no request was sent");
        }
        return lastRequest;
    }

    HttpMethod lastMethod() {
        return lastRequest().method();
    }

    URI lastUri() {
        return lastRequest().url();
    }

    String lastBodyJson() {
        return lastBodyJson;
    }

    /** Decodes the request body through the real codecs — same path a real server would see. */
    private static String extractBody(ClientRequest request) {
        BodyInserter<?, ? super ClientHttpRequest> inserter = request.body();
        MockClientHttpRequest mockRequest = new MockClientHttpRequest(request.method(), request.url());
        inserter.insert(mockRequest, context()).block();
        return mockRequest.getBodyAsString().block();
    }

    private static BodyInserter.Context context() {
        ExchangeStrategies strategies = ExchangeStrategies.withDefaults();
        return new BodyInserter.Context() {
            @Override
            public List<HttpMessageWriter<?>> messageWriters() {
                return strategies.messageWriters();
            }

            @Override
            public Optional<org.springframework.http.server.reactive.ServerHttpRequest> serverRequest() {
                return Optional.empty();
            }

            @Override
            public Map<String, Object> hints() {
                return new HashMap<>();
            }
        };
    }
}
