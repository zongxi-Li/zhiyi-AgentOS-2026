package com.kinlin.ai.gateway;

import com.kinlin.ai.security.SessionActivityProbe;
import org.springframework.http.codec.ServerSentEvent;
import reactor.core.Disposable;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.core.publisher.Sinks;
import reactor.core.scheduler.Scheduler;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.time.Duration;
import java.util.UUID;
import java.util.function.LongSupplier;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;

/**
 * 单条 SSE 流的会话复核交付门（INT-2F-4B）。
 *
 * <p>复用 {@link SessionActivityProbe#isSessionActive} 同一持久会话权威（与 HTTP
 * 认证共享，不建第二权威）。周期复核（含建连首查）按<b>查询开始时刻</b>t0 授予
 * 有效观测租期 t0+lease；撤销、过期、sid 未知、查询失败或租期耗尽一律
 * fail-closed：停止受保护事件交付并取消整条流。空闲流不依赖业务事件，
 * 由同一周期任务驱动终止。</p>
 *
 * <p>资源合同：单条流最多一个在途复核查询（CAS 护栏）；查询在专用有界阻塞
 * 调度器上执行并有订阅级超时——迟到的底层结果在订阅取消后无处投递，
 * 天然无权延长租期或复活已终止流。</p>
 */
final class SessionRecheckGate {
    private static final Logger log = LoggerFactory.getLogger(SessionRecheckGate.class);

    /** 交付门拒绝（租期耗尽或已观测到撤销），由流层转换为终止事件。 */
    static final class SessionRevokedException extends RuntimeException { }

    private final SessionActivityProbe sessionActivityProbe;
    private final UUID sid;
    private final UUID userId;
    private final Duration recheckPeriod;
    private final Duration queryTimeout;
    private final long leaseNanos;
    private final LongSupplier monotonicTime;
    private final Scheduler recheckScheduler;
    private final Runnable onRevoked;

    private final AtomicLong leaseDeadline = new AtomicLong();
    private final AtomicBoolean inFlight = new AtomicBoolean();
    private final AtomicBoolean revoked = new AtomicBoolean();
    private final AtomicBoolean closed = new AtomicBoolean();
    private final Sinks.Empty<Void> revocationSignal = Sinks.empty();
    private volatile Disposable timer;

    SessionRecheckGate(
            SessionActivityProbe sessionActivityProbe,
            UUID sid,
            UUID userId,
            Duration recheckPeriod,
            Duration queryTimeout,
            Duration lease,
            Scheduler recheckScheduler,
            Runnable onRevoked
    ) {
        this(sessionActivityProbe, sid, userId, recheckPeriod, queryTimeout, lease,
                recheckScheduler, onRevoked, System::nanoTime);
    }

    SessionRecheckGate(SessionActivityProbe sessionActivityProbe, UUID sid, UUID userId,
                       Duration recheckPeriod, Duration queryTimeout, Duration lease,
                       Scheduler recheckScheduler, Runnable onRevoked, LongSupplier monotonicTime) {
        this.sessionActivityProbe = sessionActivityProbe;
        this.sid = sid;
        this.userId = userId;
        this.recheckPeriod = recheckPeriod;
        this.queryTimeout = queryTimeout;
        this.leaseNanos = lease.toNanos();
        this.monotonicTime = monotonicTime;
        this.recheckScheduler = recheckScheduler;
        this.onRevoked = onRevoked;
    }

    /** 建连：初始租期覆盖 filter 认证观测，周期任务（t=0 首查 + 每 P）随即启动。 */
    void start(Scheduler clock) {
        // Elapsed validity must not follow host/VM wall-clock corrections.
        leaseDeadline.set(monotonicTime.getAsLong() + leaseNanos);
        timer = Flux.interval(Duration.ZERO, recheckPeriod, clock)
                .subscribe(tick -> runCheck(), error -> revoke());
    }

    /** 交付门：租期内放行；否则 fail-closed 拒绝并终止流。 */
    Mono<ServerSentEvent<String>> admit(ServerSentEvent<String> event) {
        if (!revoked.get() && monotonicTime.getAsLong() - leaseDeadline.get() < 0) {
            return Mono.just(event);
        }
        if (!revoked.get()) {
            log.warn("SSE session observation lease expired before event delivery");
        }
        revoke();
        return Mono.error(new SessionRevokedException());
    }

    /** 周期复核观测到撤销/失效/查询失败时发出的终止信号（complete 语义，只发一次）。 */
    Mono<Void> revocationSignal() {
        return revocationSignal.asMono();
    }

    boolean isRevoked() {
        return revoked.get();
    }

    /** 幂等终止：关门 + 发信号 + 停周期任务 + 计量一次。 */
    void revoke() {
        if (revoked.compareAndSet(false, true)) {
            leaseDeadline.set(0);
            disposeTimer();
            revocationSignal.tryEmitEmpty();
            onRevoked.run();
        }
    }

    /** 流结束（任何信号）后的清理：停周期任务；幂等。 */
    void close() {
        if (closed.compareAndSet(false, true)) {
            disposeTimer();
            revocationSignal.tryEmitEmpty();
        }
    }

    private void disposeTimer() {
        Disposable current = timer;
        if (current != null && !current.isDisposed()) {
            current.dispose();
        }
    }

    private void runCheck() {
        if (revoked.get() || closed.get()) {
            return;
        }
        // 单在途护栏：上一查询未决时跳过本 tick，不排队堆积
        if (!inFlight.compareAndSet(false, true)) {
            return;
        }
        long t0 = monotonicTime.getAsLong();
        Mono.fromCallable(() -> sessionActivityProbe.isSessionActive(sid, userId))
                .subscribeOn(recheckScheduler)
                .timeout(queryTimeout)
                .subscribe(
                        active -> {
                            if (inFlight.compareAndSet(true, false) && !revoked.get() && !closed.get()) {
                                if (active) {
                                    // 租期从查询开始时刻 t0 起算，不从返回时刻重新计时
                                    leaseDeadline.set(t0 + leaseNanos);
                                } else {
                                    log.info("SSE session check rejected an inactive session");
                                    revoke();
                                }
                            }
                        },
                        error -> {
                            // 查询失败/超时 = 无法确认有效：fail-closed 立即终止
                            if (inFlight.compareAndSet(true, false) && !revoked.get() && !closed.get()) {
                                log.warn("SSE session check failed; type={}", error.getClass().getSimpleName());
                                revoke();
                            }
                        });
    }
}
