package com.kinlin.ai.controller;

import com.kinlin.ai.gateway.AgentOsPaths;
import com.kinlin.ai.gateway.AiSseGatewayService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

/**
 * EVENT ownership: the runtime event SSE entry. Pure delegation to
 * {@link AiSseGatewayService} — no event parsing, no buffering, no event-type
 * rewriting (runtime event protocol is N2 scope).
 */
@RestController
@RequestMapping("/api/agentos/v2")
public class AgentOsEventController {

    private final AiSseGatewayService sseGateway;

    @Autowired
    public AgentOsEventController(AiSseGatewayService sseGateway) {
        this.sseGateway = sseGateway;
    }

    @GetMapping(value = "/runs/{runId}/events", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public Mono<ResponseEntity<Flux<ServerSentEvent<String>>>> streamRunEvents(@PathVariable String runId) {
        if (sseGateway == null) {
            return Mono.error(new IllegalStateException("RuntimeEvent SSE gateway is not configured"));
        }
        return sseGateway.openGet(AgentOsPaths.run(runId) + "/events");
    }
}
