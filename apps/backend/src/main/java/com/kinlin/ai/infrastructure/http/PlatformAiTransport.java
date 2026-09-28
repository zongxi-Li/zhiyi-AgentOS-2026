package com.kinlin.ai.infrastructure.http;

import com.kinlin.ai.client.PlatformAiClientException;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpEntity;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.util.MultiValueMap;
import org.springframework.web.reactive.function.BodyInserters;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientRequestException;
import org.springframework.web.reactive.function.client.WebClientResponseException;
import org.springframework.web.util.UriBuilder;
import reactor.core.Exceptions;

import java.net.URI;
import java.time.Duration;
import java.util.function.Function;

/**
 * Blocking JSON/multipart transport primitive shared by every platform-AI client
 * implementation. Applies the unified platform-AI command/query timeout
 * ({@code ai.service.timeout}, owned by {@link PythonServiceProperties}) and converts
 * transport failures into {@link PlatformAiClientException} — reactor/netty exception
 * types never cross into application code.
 *
 * <p>Classification: 4xx → REJECTED, 5xx → UPSTREAM_ERROR, timeout → TIMEOUT,
 * connection failure → UNAVAILABLE, anything else → INVALID_RESPONSE. Exception
 * messages preserve the original failure text so existing user-visible compositions
 * stay unchanged.</p>
 */
@Component
class PlatformAiTransport {

    private final WebClient transport;
    private final PythonServiceProperties properties;

    PlatformAiTransport(WebClient pythonTransport, PythonServiceProperties properties) {
        this.transport = pythonTransport;
        this.properties = properties;
    }

    <T> T postJson(String uri, Object body, Class<T> responseType) {
        return invoke(() -> transport.post().uri(uri)
                .bodyValue(body)
                .retrieve()
                .bodyToMono(responseType)
                .timeout(commandTimeout())
                .block());
    }

    <T> T postJson(String uri, Object body, ParameterizedTypeReference<T> responseType) {
        return invoke(() -> transport.post().uri(uri)
                .bodyValue(body)
                .retrieve()
                .bodyToMono(responseType)
                .timeout(commandTimeout())
                .block());
    }

    <T> T postMultipart(String uri, MultiValueMap<String, HttpEntity<?>> parts,
                        ParameterizedTypeReference<T> responseType) {
        return invoke(() -> transport.post().uri(uri)
                .contentType(MediaType.MULTIPART_FORM_DATA)
                .body(BodyInserters.fromMultipartData(parts))
                .retrieve()
                .bodyToMono(responseType)
                .timeout(commandTimeout())
                .block());
    }

    <T> T get(Function<UriBuilder, URI> uri, ParameterizedTypeReference<T> responseType) {
        return invoke(() -> transport.get()
                .uri(uri)
                .retrieve()
                .bodyToMono(responseType)
                .timeout(commandTimeout())
                .block());
    }

    /** String-template variant; identical semantics to {@code WebClient.uri(String, Object...)}. */
    <T> T get(String uri, ParameterizedTypeReference<T> responseType, Object... uriVariables) {
        return invoke(() -> transport.get()
                .uri(uri, uriVariables)
                .retrieve()
                .bodyToMono(responseType)
                .timeout(commandTimeout())
                .block());
    }

    <T> T delete(String uri, ParameterizedTypeReference<T> responseType) {
        return invoke(() -> transport.delete()
                .uri(uri)
                .retrieve()
                .bodyToMono(responseType)
                .timeout(commandTimeout())
                .block());
    }

    private Duration commandTimeout() {
        return Duration.ofMillis(properties.getTimeout());
    }

    private <T> T invoke(java.util.function.Supplier<T> call) {
        try {
            return call.get();
        } catch (WebClientResponseException error) {
            throw new PlatformAiClientException(
                    error.getStatusCode().is4xxClientError()
                            ? PlatformAiClientException.Type.REJECTED
                            : PlatformAiClientException.Type.UPSTREAM_ERROR,
                    error.getMessage(),
                    error.getStatusCode().value(),
                    error
            );
        } catch (WebClientRequestException error) {
            throw new PlatformAiClientException(
                    PlatformAiClientException.Type.UNAVAILABLE, error.getMessage(), -1, error);
        } catch (Exception error) {
            Throwable unwrapped = Exceptions.unwrap(error);
            if (TransportErrorClassifier.isTimeout(unwrapped)) {
                throw new PlatformAiClientException(
                        PlatformAiClientException.Type.TIMEOUT, failureText(error, unwrapped), -1, unwrapped);
            }
            if (TransportErrorClassifier.isConnectionFailure(unwrapped)) {
                throw new PlatformAiClientException(
                        PlatformAiClientException.Type.UNAVAILABLE, failureText(error, unwrapped), -1, unwrapped);
            }
            throw new PlatformAiClientException(
                    PlatformAiClientException.Type.INVALID_RESPONSE, failureText(error, error), -1, error);
        }
    }

    /** Today's observers see the block()-rethrown message; preserve it verbatim. */
    private String failureText(Throwable rethrown, Throwable classified) {
        return rethrown.getMessage() != null ? rethrown.getMessage() : classified.getMessage();
    }
}
