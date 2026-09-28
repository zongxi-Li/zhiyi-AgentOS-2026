package com.kinlin.ai.controller;

import com.kinlin.ai.gateway.AiSseGatewayService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.asyncDispatch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.request;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/** EVENT ownership: the SSE entry delegates to the SSE gateway and nothing else. */
class AgentOsEventControllerTest {

    private AiSseGatewayService sseGateway;
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        sseGateway = mock(AiSseGatewayService.class);
        mockMvc = MockMvcBuilders.standaloneSetup(new AgentOsEventController(sseGateway)).build();
    }

    @Test
    void streamRunEventsDelegatesToTheSseGatewayWithoutTouchingThePayload() throws Exception {
        when(sseGateway.openGet("/ai/agentos/v2/runs/run_1/events")).thenReturn(Mono.just(
                ResponseEntity.ok()
                        .contentType(MediaType.TEXT_EVENT_STREAM)
                        .body(Flux.just(ServerSentEvent.builder("hello").event("RuntimeEvent").build()))
        ));

        MvcResult started = mockMvc.perform(get("/api/agentos/v2/runs/{runId}/events", "run_1"))
                .andExpect(request().asyncStarted())
                .andReturn();
        mockMvc.perform(asyncDispatch(started))
                .andExpect(status().isOk())
                .andExpect(content().contentTypeCompatibleWith(MediaType.TEXT_EVENT_STREAM))
                .andExpect(content().string(org.hamcrest.Matchers.containsString("hello")));

        verify(sseGateway).openGet("/ai/agentos/v2/runs/run_1/events");
    }

    @Test
    void missingSseGatewayFailsTheStreamExplicitly() {
        AtomicReference<Throwable> failure = new AtomicReference<>();
        new AgentOsEventController(null).streamRunEvents("run_1")
                .subscribe(ignored -> { }, failure::set);

        assertInstanceOf(IllegalStateException.class, failure.get());
        assertEquals("RuntimeEvent SSE gateway is not configured", failure.get().getMessage());
    }
}
