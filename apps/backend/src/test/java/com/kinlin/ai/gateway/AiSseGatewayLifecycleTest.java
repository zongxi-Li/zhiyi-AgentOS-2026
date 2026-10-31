package com.kinlin.ai.gateway;

import com.kinlin.ai.security.AuthenticatedUserContext;
import com.kinlin.ai.security.SessionActivityProbe;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Test;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.core.io.buffer.DefaultDataBufferFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.web.reactive.function.client.ClientResponse;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.core.publisher.SignalType;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/** 真实 WebClient SSE 解码 + 生产网关；受控上游分别证明四种终止只释放一次。 */
class AiSseGatewayLifecycleTest {
    private final SimpleMeterRegistry registry = new SimpleMeterRegistry();
    private final AtomicBoolean sessionActive = new AtomicBoolean(true);
    private final AtomicInteger upstreamTerminations = new AtomicInteger();
    private final AtomicReference<SignalType> upstreamSignal = new AtomicReference<>();
    // 与生产 Spring singleton 相同，保持 Gauge 所观测状态的所有者存活。
    private AiSseGatewayService gateway;

    private Flux<ServerSentEvent<String>> open(Flux<DataBuffer> tail) {
        var forwarder = mock(TrustedUserContextForwarder.class);
        when(forwarder.requireCurrent()).thenReturn(new AuthenticatedUserContext(
                UUID.randomUUID(), "lifecycle", "USER", UUID.randomUUID(), null, null));
        var probe = mock(SessionActivityProbe.class);
        when(probe.isSessionActive(any(), any())).thenAnswer(ignored -> sessionActive.get());
        Flux<DataBuffer> source = Flux.concat(Flux.defer(() -> Flux.just(
                new DefaultDataBufferFactory().wrap("event: model.output.delta\ndata: protected\n\n"
                        .getBytes(StandardCharsets.UTF_8)))), tail)
                .doFinally(signal -> {
                    upstreamSignal.set(signal);
                    upstreamTerminations.incrementAndGet();
                });
        AtomicBoolean subscribed = new AtomicBoolean();
        // 真实 HTTP body 只允许一次订阅。ClientResponse 出错释放 body 时可能再次
        // 尝试订阅；冷 Flux mock 不得把该释放动作伪装成第二条真实上游流。
        Flux<DataBuffer> upstream = Flux.defer(() -> subscribed.compareAndSet(false, true)
                ? source : Flux.error(new IllegalStateException("HTTP response body already consumed")));
        WebClient transport = WebClient.builder().exchangeFunction(request -> Mono.just(
                ClientResponse.create(HttpStatus.OK)
                        .header("Content-Type", MediaType.TEXT_EVENT_STREAM_VALUE)
                        .body(upstream).build())).build();
        gateway = new AiSseGatewayService(transport, 30_000, 60_000, 20, 1000, 5000,
                forwarder, probe, registry);
        return gateway.openGet("/controlled-events").block(Duration.ofSeconds(5)).getBody();
    }

    @Test
    void completeReleasesOneOpenedStreamExactlyOnce() {
        var events = open(Flux.empty()).collectList().block(Duration.ofSeconds(5));
        assertThat(events).singleElement().satisfies(event -> assertThat(event.data()).isEqualTo("protected"));
        awaitRelease(1, 0);
        assertThat(upstreamSignal.get()).isEqualTo(SignalType.ON_COMPLETE);
    }

    @Test
    void upstreamErrorKeepsExistingTerminalProtocolAndReleasesExactlyOnce() {
        var events = open(Flux.error(new IllegalStateException("controlled upstream failure")))
                .collectList().block(Duration.ofSeconds(5));
        assertThat(events).hasSize(2);
        assertThat(events.get(0).data()).isEqualTo("protected");
        assertThat(events.get(1).event()).isEqualTo("error");
        assertThat(events.get(1).data()).contains("AI_STREAM_INTERRUPTED");
        awaitRelease(1, 0);
        assertThat(counter("upstream_error")).isEqualTo(1);
        assertThat(upstreamSignal.get()).isEqualTo(SignalType.ON_ERROR);
    }

    @Test
    void repeatedCancelReleasesExactlyOnce() throws InterruptedException {
        var first = new CountDownLatch(1);
        var failure = new AtomicReference<Throwable>();
        var subscription = open(Flux.never()).subscribe(event -> first.countDown(), failure::set);
        try {
            assertThat(first.await(5, TimeUnit.SECONDS)).isTrue();
            assertThat(registry.get("kinlin.sse.streams.active").gauge().value()).isEqualTo(1);
        } finally {
            subscription.dispose();
            subscription.dispose();
        }
        assertThat(failure.get()).isNull();
        awaitRelease(0, 1);
        assertThat(upstreamSignal.get()).isEqualTo(SignalType.CANCEL);
    }

    @Test
    void sessionRevocationCompletesOnceAndCancelsUpstreamOnce() throws InterruptedException {
        var first = new CountDownLatch(1);
        var finished = new CountDownLatch(1);
        var failure = new AtomicReference<Throwable>();
        List<ServerSentEvent<String>> events = new CopyOnWriteArrayList<>();
        var subscription = open(Flux.never()).doFinally(ignored -> finished.countDown()).subscribe(event -> {
            events.add(event);
            first.countDown();
        }, failure::set);
        try {
            assertThat(first.await(5, TimeUnit.SECONDS)).isTrue();
            sessionActive.set(false);
            assertThat(finished.await(5, TimeUnit.SECONDS)).isTrue();
        } finally {
            subscription.dispose();
            subscription.dispose();
        }
        assertThat(failure.get()).isNull();
        assertThat(events).extracting(ServerSentEvent::event)
                .containsExactly("model.output.delta", "auth.invalidated");
        awaitRelease(1, 0);
        assertThat(counter("session_revoked")).isEqualTo(1);
        assertThat(upstreamSignal.get()).isEqualTo(SignalType.CANCEL);
    }

    private double counter(String suffix) {
        return registry.find("kinlin.sse.streams." + suffix).counters()
                .stream().mapToDouble(counter -> counter.count()).sum();
    }

    private void awaitRelease(double completed, double cancelled) {
        // block/onComplete 可先于 doFinally 返回；等待真正的终止计量与上游清理落地。
        await().atMost(Duration.ofSeconds(5)).untilAsserted(() -> {
            assertThat(counter("opened")).isEqualTo(1);
            assertThat(counter("completed")).isEqualTo(completed);
            assertThat(counter("cancelled")).isEqualTo(cancelled);
            assertThat(registry.get("kinlin.sse.streams.active").gauge().value()).isZero();
            assertThat(upstreamTerminations.get()).isEqualTo(1);
        });
    }
}
