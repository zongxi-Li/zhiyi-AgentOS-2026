package com.kinlin.ai.client;

/**
 * Stable transport-failure boundary for the platform-AI client family.
 *
 * <p>Raised by platform-AI client implementations instead of raw reactor/netty
 * exceptions ({@code WebClientRequestException}, {@code WebClientResponseException},
 * {@code TimeoutException}, …). Application services see only this type and decide
 * the business outcome (fallback, empty result, rethrow as business error) — a
 * transport error is never itself a business fallback.</p>
 *
 * <p>The message preserves the original failure text so existing user-visible
 * compositions (e.g. "构建知识图谱失败: …") stay unchanged; {@link #upstreamStatus()}
 * carries the upstream HTTP status when the failure was status-derived (-1 otherwise).</p>
 */
public class PlatformAiClientException extends RuntimeException {

    public enum Type {
        /** Upstream did not answer within the configured request timeout. */
        TIMEOUT,
        /** Connection could not be established or DNS resolution failed. */
        UNAVAILABLE,
        /** Upstream answered 4xx — the request was rejected. */
        REJECTED,
        /** Upstream answered 5xx. */
        UPSTREAM_ERROR,
        /** Response could not be decoded into the contracted shape. */
        INVALID_RESPONSE
    }

    private final Type type;
    private final int upstreamStatus;

    public PlatformAiClientException(Type type, String message) {
        this(type, message, -1, null);
    }

    public PlatformAiClientException(Type type, String message, int upstreamStatus, Throwable cause) {
        super(message, cause);
        this.type = type;
        this.upstreamStatus = upstreamStatus;
    }

    public Type type() {
        return type;
    }

    /** Upstream HTTP status when the failure was derived from a status code, else -1. */
    public int upstreamStatus() {
        return upstreamStatus;
    }
}
