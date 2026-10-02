package com.kinlin.ai.gateway;

import io.micrometer.core.instrument.MeterRegistry;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.core.publisher.SignalType;

import java.time.Duration;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;

/** Non-buffering SSE bridge with separate inactivity and total-duration limits. */
@Slf4j
@Service
public class AiSseGatewayService {

    private static final ParameterizedTypeReference<ServerSentEvent<String>> SSE_TYPE =
            new ParameterizedTypeReference<>() { };

    private final WebClient webClient;
    private final Duration idleTimeout;
    private final Duration maximumDuration;
    private final TrustedUserContextForwarder userContextForwarder;

    // J1.4C §六：SSE 流生命周期指标，全部无 tag（runId/userId 禁止进入）。
    // idle/max/upstream 三类终止在各自 onErrorResume 转换点计数（事实源头），
    // opened/completed/cancelled/active 在下游订阅生命周期上计数。
    private final AtomicLong activeStreams;
    private final MeterRegistry meterRegistry;

    @Autowired
    public AiSseGatewayService(
            WebClient pythonTransport,
            @Value("${ai.sse.idle-timeout-ms:240000}") long idleTimeoutMs,
            @Value("${ai.sse.max-duration-ms:1800000}") long maximumDurationMs,
            TrustedUserContextForwarder userContextForwarder,
            MeterRegistry meterRegistry
    ) {
        if (idleTimeoutMs <= 0 || maximumDurationMs <= 0) {
            throw new IllegalArgumentException("SSE timeouts must be positive");
        }
        this.webClient = pythonTransport;
        this.idleTimeout = Duration.ofMillis(idleTimeoutMs);
        this.maximumDuration = Duration.ofMillis(maximumDurationMs);
        this.userContextForwarder = userContextForwarder;
        this.meterRegistry = meterRegistry;
        this.activeStreams = meterRegistry.gauge("kinlin.sse.streams.active", new AtomicLong());
    }

    /** Test seam: takes a pre-built transport so base-URL wiring stays with {@code PythonClientFactory}. */
    AiSseGatewayService(WebClient transport, long idleTimeoutMs, long maximumDurationMs) {
        this(transport, idleTimeoutMs, maximumDurationMs,
                new TrustedUserContextForwarder(),
                new io.micrometer.core.instrument.simple.SimpleMeterRegistry());
    }

    public Mono<ResponseEntity<Flux<ServerSentEvent<String>>>> openPost(String path, Object body) {
        var userContext = userContextForwarder.requireCurrent();
        return webClient.post()
                .uri(path)
                .contentType(MediaType.APPLICATION_JSON)
                .accept(MediaType.TEXT_EVENT_STREAM)
                .headers(headers -> userContextForwarder.apply(headers, userContext))
                .bodyValue(body == null ? Map.of() : body)
                .retrieve()
                .onStatus(HttpStatusCode::isError, upstream -> upstreamError(upstream.statusCode()))
                .toEntityFlux(SSE_TYPE)
                .transform(this::toDownstreamResponse)
                .onErrorResume(this::mapConnectionError);
    }

    /** Open the RuntimeEvent stream without introducing a second event source or buffering layer. */
    public Mono<ResponseEntity<Flux<ServerSentEvent<String>>>> openGet(String path) {
        var userContext = userContextForwarder.requireCurrent();
        return webClient.get()
                .uri(path)
                .accept(MediaType.TEXT_EVENT_STREAM)
                .headers(headers -> userContextForwarder.apply(headers, userContext))
                .retrieve()
                .onStatus(HttpStatusCode::isError, upstream -> upstreamError(upstream.statusCode()))
                .toEntityFlux(SSE_TYPE)
                .transform(this::toDownstreamResponse)
                .onErrorResume(this::mapConnectionError);
    }

    private Mono<? extends Throwable> upstreamError(HttpStatusCode statusCode) {
        return Mono.error(new SseUpstreamStatusException(statusCode.value()));
    }

    private Mono<ResponseEntity<Flux<ServerSentEvent<String>>>> toDownstreamResponse(
            Mono<ResponseEntity<Flux<ServerSentEvent<String>>>> upstreamResponse
    ) {
        return upstreamResponse.map(upstream -> {
            Flux<ServerSentEvent<String>> body = upstream.getBody() == null
                    ? Flux.empty()
                    : upstream.getBody();
            Flux<ServerSentEvent<String>> stream = body
                    .timeout(idleTimeout, Flux.error(new SseIdleTimeoutException()))
                    .takeUntilOther(Mono.delay(maximumDuration)
                            .flatMap(ignored -> Mono.<Void>error(new SseMaximumDurationException())))
                    .onErrorResume(SseIdleTimeoutException.class,
                            ignored -> Flux.just(terminalErrorEvent("SSE_IDLE_TIMEOUT",
                                    "kinlin.sse.streams.idle_timeout")))
                    .onErrorResume(SseMaximumDurationException.class,
                            ignored -> Flux.just(terminalErrorEvent("SSE_MAX_DURATION",
                                    "kinlin.sse.streams.max_duration")))
                    .onErrorResume(error -> {
                        log.warn("SSE upstream stream terminated. type={}", error.getClass().getSimpleName());
                        meterRegistry.counter("kinlin.sse.streams.upstream_error").increment();
                        return Flux.just(errorEvent("AI_STREAM_INTERRUPTED"));
                    })
                    .doOnCancel(() -> log.info("SSE downstream cancelled; upstream subscription cancelled"));

            return ResponseEntity.ok()
                    .contentType(MediaType.TEXT_EVENT_STREAM)
                    .header("Cache-Control", "no-cache, no-transform")
                    .header("X-Accel-Buffering", "no")
                    .body(instrument(stream));
        });
    }

    private Flux<ServerSentEvent<String>> instrument(Flux<ServerSentEvent<String>> stream) {
        return stream
                .doOnSubscribe(ignored -> {
                    meterRegistry.counter("kinlin.sse.streams.opened").increment();
                    activeStreams.incrementAndGet();
                })
                .doOnCancel(() -> {
                    meterRegistry.counter("kinlin.sse.streams.cancelled").increment();
                    activeStreams.decrementAndGet();
                })
                .doFinally(signal -> {
                    if (signal == SignalType.ON_COMPLETE) {
                        meterRegistry.counter("kinlin.sse.streams.completed").increment();
                        activeStreams.decrementAndGet();
                    } else if (signal == SignalType.ON_ERROR) {
                        activeStreams.decrementAndGet();
                    }
                });
    }

    /** 终止类错误事件：计数 + 错误事件一次完成（idle/max 专用）。 */
    private ServerSentEvent<String> terminalErrorEvent(String code, String counterName) {
        meterRegistry.counter(counterName).increment();
        return errorEvent(code);
    }

    private Mono<ResponseEntity<Flux<ServerSentEvent<String>>>> mapConnectionError(Throwable error) {
        if (error instanceof SseUpstreamStatusException statusError) {
            return Mono.just(errorResponse(
                    statusError.status < 500 ? HttpStatus.valueOf(statusError.status) : HttpStatus.BAD_GATEWAY,
                    statusError.status < 500 ? "AI_STREAM_REJECTED" : "AI_STREAM_UPSTREAM_ERROR"
            ));
        }
        log.warn("SSE upstream connection failed. type={}", error.getClass().getSimpleName());
        return Mono.just(errorResponse(HttpStatus.SERVICE_UNAVAILABLE, "AI_STREAM_UNAVAILABLE"));
    }

    private ResponseEntity<Flux<ServerSentEvent<String>>> errorResponse(HttpStatus status, String code) {
        return ResponseEntity.status(status)
                .contentType(MediaType.TEXT_EVENT_STREAM)
                .header("Cache-Control", "no-cache, no-transform")
                .header("X-Accel-Buffering", "no")
                .body(Flux.just(errorEvent(code)));
    }

    private ServerSentEvent<String> errorEvent(String code) {
        return ServerSentEvent.builder("{\"error\":\"" + code + "\"}").event("error").build();
    }

    private static final class SseIdleTimeoutException extends RuntimeException { }

    private static final class SseMaximumDurationException extends RuntimeException { }

    private static final class SseUpstreamStatusException extends RuntimeException {
        private final int status;

        private SseUpstreamStatusException(int status) {
            this.status = status;
        }
    }
}
