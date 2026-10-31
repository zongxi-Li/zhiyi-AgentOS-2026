package com.kinlin.ai.controller;

import com.kinlin.ai.gateway.AiSseGatewayService;
import com.kinlin.ai.interceptor.RateLimitInterceptor;
import com.kinlin.ai.service.LoginSessionService;
import com.kinlin.ai.util.JwtUtil;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.data.jpa.mapping.JpaMetamodelMappingContext;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.ResultActions;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.asyncDispatch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.request;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/** EVENT ownership: the SSE entry delegates to the SSE gateway and nothing else. */
@WebMvcTest(AgentOsEventController.class)
@AutoConfigureMockMvc(addFilters = false)
class AgentOsEventControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private AiSseGatewayService sseGateway;

    @MockBean
    private RateLimitInterceptor rateLimitInterceptor;

    @MockBean
    private JwtUtil jwtUtil;

    @MockBean
    private LoginSessionService loginSessionService;

    @MockBean
    private JpaMetamodelMappingContext jpaMetamodelMappingContext;

    @BeforeEach
    void setUp() {
        when(rateLimitInterceptor.preHandle(any(), any(), any())).thenReturn(true);
    }

    @Test
    void streamRunEventsDelegatesToTheSseGatewayWithoutTouchingThePayload() throws Exception {
        when(sseGateway.openGet("/ai/agentos/v2/runs/run_1/events")).thenReturn(Mono.just(
                ResponseEntity.ok()
                        .contentType(MediaType.TEXT_EVENT_STREAM)
                        .body(Flux.just(ServerSentEvent.builder("hello").event("RuntimeEvent").build()))
        ));

        MvcResult started = mockMvc.perform(get("/api/agentos/v2/runs/{runId}/events", "run_1")
                        .accept(MediaType.TEXT_EVENT_STREAM))
                .andExpect(request().asyncStarted())
                .andReturn();
        awaitSseCompletion(mockMvc.perform(asyncDispatch(started)))
                .andExpect(status().isOk())
                .andExpect(content().contentTypeCompatibleWith(MediaType.TEXT_EVENT_STREAM))
                .andExpect(content().string(org.hamcrest.Matchers.containsString("hello")));

        verify(sseGateway).openGet("/ai/agentos/v2/runs/run_1/events");
    }

    @Test
    void copilotStreamUsesTheExistingPostSseGateway() throws Exception {
        when(sseGateway.openPost(any(), any())).thenReturn(Mono.just(ResponseEntity.ok()
                .contentType(MediaType.TEXT_EVENT_STREAM)
                .body(Flux.just(ServerSentEvent.builder("{\"type\":\"content\",\"content\":\"partial\"}").build()))));
        MvcResult started = mockMvc.perform(post("/api/agentos/v2/runs/run_1/copilot/messages/stream")
                .contentType(MediaType.APPLICATION_JSON).accept(MediaType.TEXT_EVENT_STREAM)
                .content("{\"operationId\":\"op\",\"content\":\"hello\",\"reasoningEffort\":\"high\"}"))
                .andExpect(request().asyncStarted()).andReturn();
        awaitSseCompletion(mockMvc.perform(asyncDispatch(started))).andExpect(status().isOk())
                .andExpect(content().string(org.hamcrest.Matchers.containsString("partial")));
        verify(sseGateway).openPost(org.mockito.ArgumentMatchers.eq("/ai/agentos/v2/runs/run_1/copilot/messages/stream"), any());
    }

    @Test
    void deferredCopilotBodyMustFinishBeforeResponseAssertion() throws Exception {
        var body = reactor.core.publisher.Sinks.<ServerSentEvent<String>>one();
        var subscribed = new java.util.concurrent.CountDownLatch(1);
        when(sseGateway.openPost(any(), any())).thenReturn(Mono.just(ResponseEntity.ok()
                .contentType(MediaType.TEXT_EVENT_STREAM)
                .body(body.asMono().flux().doOnSubscribe(ignored -> subscribed.countDown()))));
        MvcResult started = mockMvc.perform(post("/api/agentos/v2/runs/run_1/copilot/messages/stream")
                        .contentType(MediaType.APPLICATION_JSON).accept(MediaType.TEXT_EVENT_STREAM)
                        .content("{\"content\":\"hello\"}"))
                .andExpect(request().asyncStarted()).andReturn();
        ResultActions streaming = mockMvc.perform(asyncDispatch(started))
                .andExpect(request().asyncStarted());
        org.junit.jupiter.api.Assertions.assertTrue(subscribed.await(5, java.util.concurrent.TimeUnit.SECONDS));
        // 外层 Mono 已完成，但 SSE body 尚无事件；不能在这个阶段断言最终响应体。
        streaming.andExpect(content().string(""));
        assertEquals(reactor.core.publisher.Sinks.EmitResult.OK,
                body.tryEmitValue(ServerSentEvent.builder("partial").build()));
        awaitSseCompletion(streaming).andExpect(status().isOk())
                .andExpect(content().string(org.hamcrest.Matchers.containsString("partial")));
        verify(sseGateway).openPost(org.mockito.ArgumentMatchers.eq("/ai/agentos/v2/runs/run_1/copilot/messages/stream"), any());
    }

    /** Mono<ResponseEntity<Flux<...>>> 的响应体会再开启一轮异步请求。 */
    private ResultActions awaitSseCompletion(ResultActions response) throws Exception {
        MvcResult streaming = response.andReturn();
        if (streaming.getRequest().isAsyncStarted()) {
            // 等待真实 MVC SSE 写出完成，而不是仅等待上游 Flux 的 onComplete。
            streaming.getAsyncResult(10_000);
            response = mockMvc.perform(asyncDispatch(streaming));
        }
        return response.andExpect(request().asyncNotStarted());
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
