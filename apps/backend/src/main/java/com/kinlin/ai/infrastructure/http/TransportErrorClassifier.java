package com.kinlin.ai.infrastructure.http;

import java.net.ConnectException;
import java.net.UnknownHostException;
import java.util.concurrent.TimeoutException;

/**
 * Transport-level error classification shared by every Java-to-Python client family.
 *
 * <p>Classification only — mapping to HTTP status/business error codes stays with each
 * client family (AgentOS uses the N1.1 envelope, platform-AI keeps its public contract,
 * the AI proxy maps to AI_UPSTREAM_* codes).</p>
 */
public final class TransportErrorClassifier {

    private TransportErrorClassifier() {
    }

    public static boolean isTimeout(Throwable error) {
        return error instanceof TimeoutException
                || error.getClass().getSimpleName().contains("Timeout");
    }

    public static boolean isConnectionFailure(Throwable error) {
        if (error instanceof org.springframework.web.reactive.function.client.WebClientRequestException requestError) {
            Throwable cause = requestError.getCause();
            return cause instanceof ConnectException || cause instanceof UnknownHostException
                    || (cause != null && cause.getClass().getSimpleName().contains("Connect"));
        }
        Throwable current = error;
        while (current != null) {
            if (current instanceof ConnectException || current instanceof UnknownHostException
                    || current.getClass().getSimpleName().contains("ConnectException")) {
                return true;
            }
            current = current.getCause();
        }
        return false;
    }

    public static String describe(Throwable error) {
        return error == null ? "unknown" : error.getClass().getSimpleName();
    }
}
