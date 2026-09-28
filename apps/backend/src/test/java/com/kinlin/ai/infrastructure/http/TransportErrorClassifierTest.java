package com.kinlin.ai.infrastructure.http;

import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpHeaders;
import org.springframework.web.reactive.function.client.WebClientRequestException;

import java.net.ConnectException;
import java.net.URI;
import java.util.concurrent.TimeoutException;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class TransportErrorClassifierTest {

    @Test
    void classifiesReactorAndJvmTimeouts() {
        assertTrue(TransportErrorClassifier.isTimeout(new TimeoutException("reactor timeout")));
        assertFalse(TransportErrorClassifier.isTimeout(new ConnectException("connection refused")));
    }

    @Test
    void classifiesConnectionFailuresIncludingWrappedCauses() {
        assertTrue(TransportErrorClassifier.isConnectionFailure(new ConnectException("refused")));
        assertTrue(TransportErrorClassifier.isConnectionFailure(
                new RuntimeException(new ConnectException("wrapped refused"))));
        assertTrue(TransportErrorClassifier.isConnectionFailure(
                new WebClientRequestException(new ConnectException("cause"),
                        HttpMethod.GET, URI.create("http://127.0.0.1:1"), HttpHeaders.EMPTY)));
        assertFalse(TransportErrorClassifier.isConnectionFailure(new TimeoutException("timeout")));
        assertFalse(TransportErrorClassifier.isConnectionFailure(
                new WebClientRequestException(new TimeoutException("cause"),
                        HttpMethod.GET, URI.create("http://127.0.0.1:1"), HttpHeaders.EMPTY)));
    }

    @Test
    void describesErrorsBySimpleNameOnly() {
        assertEquals("TimeoutException", TransportErrorClassifier.describe(new TimeoutException("x")));
        assertEquals("unknown", TransportErrorClassifier.describe(null));
    }
}
