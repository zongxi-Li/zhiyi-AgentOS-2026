package com.kinlin.ai.architecture;

import org.junit.jupiter.api.Test;
import org.springframework.core.annotation.AnnotatedElementUtils;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.RequestMappingHandlerMapping;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.Set;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.mock;

/** Checks Spring's registered routes, including composed mapping annotations and prefix composition. */
class StaticQueryRouteArchitectureTest {
    private record Transport(String handler, String path, String response, String produces) { }
    private static final Set<Transport> TRANSPORTS = Set.of(
            new Transport("AiServiceProxyController#proxy", "/ai/**", "org.springframework.http.ResponseEntity<byte[]>", "[]"),
            new Transport("AgentOsArtifactController#downloadArtifact", "/api/agentos/v2/runs/{runId}/artifacts/{manifestId}/download",
                    "org.springframework.http.ResponseEntity<byte[]>", "[]"),
            new Transport("FileController#downloadFile", "/files/download/{type}/{filename:.+}",
                    "org.springframework.http.ResponseEntity<org.springframework.core.io.Resource>", "[]"),
            new Transport("AgentOsEventController#streamRunEvents", "/api/agentos/v2/runs/{runId}/events",
                    "reactor.core.publisher.Mono<org.springframework.http.ResponseEntity<reactor.core.publisher.Flux<org.springframework.http.codec.ServerSentEvent<java.lang.String>>>>",
                    "[text/event-stream]"));

    @Test
    void everyRegisteredStaticGetUsesStrictProjectionOrAnExactTransportException() throws Exception {
        var controllers = new ArrayList<Object>();
        try (var files = Files.list(Path.of("src/main/java/com/kinlin/ai/controller"))) {
            for (var source : files.filter(path -> path.toString().endsWith(".java")).toList()) {
                var type = Class.forName("com.kinlin.ai.controller." + source.getFileName().toString().replace(".java", ""));
                if (AnnotatedElementUtils.hasAnnotation(type, RestController.class)) controllers.add(mock(type));
            }
        }
        var mvc = MockMvcBuilders.standaloneSetup(controllers.toArray()).build();
        var mapping = mvc.getDispatcherServlet().getWebApplicationContext().getBean(RequestMappingHandlerMapping.class);
        var seenTransports = new HashSet<Transport>();
        int checked = 0;
        for (var entry : mapping.getHandlerMethods().entrySet()) {
            var route = entry.getKey();
            if (!route.getMethodsCondition().getMethods().isEmpty()
                    && !route.getMethodsCondition().getMethods().contains(RequestMethod.GET)) continue;
            var method = entry.getValue().getMethod();
            var type = method.getDeclaringClass();
            for (var path : route.getPatternValues()) {
                if (QueryProjectionArchitectureTest.strictOutputChecked(type, method)) { checked++; continue; }
                var transport = new Transport(type.getSimpleName() + "#" + method.getName(), path,
                        method.getGenericReturnType().getTypeName(), route.getProducesCondition().toString());
                assertTrue(TRANSPORTS.contains(transport), "unprojected GET or widened transport exception: " + transport);
                seenTransports.add(transport);
            }
        }
        assertTrue(checked > 0, "must inspect real Spring mappings");
        assertEquals(TRANSPORTS, seenTransports, "stale or removed transport exceptions must be removed deliberately");
    }
}
