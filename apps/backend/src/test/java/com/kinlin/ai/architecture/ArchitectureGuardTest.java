package com.kinlin.ai.architecture;

import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

/**
 * Architecture guards for the J1.1 backend boundary convergence.
 *
 * <p>Source-level guards (no bytecode analysis dependency). They enforce the decisions
 * frozen in {@code apps/backend/ARCHITECTURE.md}:</p>
 *
 * <ul>
 *   <li>Controllers never operate transport (WebClient / RestTemplate).</li>
 *   <li>RestTemplate exists only inside the legacy agent boundary.</li>
 *   <li>The Python root and {@code ai.service.*} / {@code agent.*} property placeholders
 *       are resolved only by the infrastructure transport owner; SSE timeouts only by
 *       the SSE gateway.</li>
 *   <li>Business services never wire a base URL or construct an HTTP client; base-URL
 *       wiring belongs to the client factory and the gateway transport classes.</li>
 *   <li>The AgentOS upstream path is reachable only through the single AgentOS
 *       transport family.</li>
 *   <li>Only the SSE gateway opens upstream event streams; WebSocket is a marked
 *       LEGACY transport and never carries AgentOS events.</li>
 *   <li>No ACG semantic implementation leaks into the Java platform.</li>
 * </ul>
 */
class ArchitectureGuardTest {

    private static final Map<String, String> SOURCES = new HashMap<>();
    private static Path mainJava;

    @BeforeAll
    static void loadMainSources() throws IOException {
        mainJava = Path.of("src", "main", "java");
        assumeTrue(Files.isDirectory(mainJava), "run from the backend module directory");
        try (Stream<Path> paths = Files.walk(mainJava)) {
            paths.filter(path -> path.toString().endsWith(".java"))
                    .forEach(path -> {
                        try {
                            SOURCES.put(mainJava.relativize(path).toString().replace('\\', '/'),
                                    Files.readString(path));
                        } catch (IOException failed) {
                            throw new IllegalStateException(failed);
                        }
                    });
        }
    }

    private static List<String> matchingFiles(String needle) {
        return SOURCES.entrySet().stream()
                .filter(entry -> entry.getValue().contains(needle))
                .map(Map.Entry::getKey)
                .sorted()
                .toList();
    }

    private static List<String> filesUnder(String prefix) {
        return SOURCES.keySet().stream().filter(key -> key.startsWith(prefix)).sorted().toList();
    }

    @Test
    void controllersOperateNoTransport() {
        List<String> offenders = filesUnder("com/kinlin/ai/controller/").stream()
                .filter(key -> {
                    String content = SOURCES.get(key);
                    return content.contains("WebClient") || content.contains("RestTemplate")
                            || content.contains("exchangeToMono") || content.contains(".block(");
                })
                .toList();

        assertTrue(offenders.isEmpty(), "controllers must not operate transport: " + offenders);
    }

    @Test
    void restTemplateIsConfinedToTheLegacyBoundary() {
        List<String> offenders = matchingFiles("RestTemplate").stream()
                .filter(key -> !key.startsWith("com/kinlin/ai/legacy/"))
                .toList();

        assertTrue(offenders.isEmpty(), "RestTemplate outside the legacy boundary: " + offenders);
    }

    @Test
    void pythonServiceConfigIsReadOnlyByTheTransportOwner() {
        List<String> offenders = Stream.concat(
                        matchingFiles("${ai.service.").stream(),
                        matchingFiles("${agent.").stream())
                .distinct()
                .toList();

        assertTrue(offenders.isEmpty(),
                "ai.service.*/agent.* config must be owned by infrastructure transport: " + offenders);
    }

    @Test
    void sseTimeoutConfigIsOwnedOnlyByTheSseGateway() {
        List<String> offenders = matchingFiles("${ai.sse.").stream()
                .filter(key -> !key.equals("com/kinlin/ai/gateway/AiSseGatewayService.java"))
                .toList();

        assertTrue(offenders.isEmpty(), "ai.sse.* config outside the SSE gateway: " + offenders);
    }

    @Test
    void baseUrlWiringNeverHappensInBusinessServices() {
        List<String> offenders = matchingFiles(".baseUrl(").stream()
                .filter(key -> !key.startsWith("com/kinlin/ai/infrastructure/http/")
                        && !key.startsWith("com/kinlin/ai/gateway/"))
                .toList();

        assertTrue(offenders.isEmpty(), "base URL wiring outside transport owners: " + offenders);
    }

    @Test
    void webClientConstructionIsLimitedToConfigAndFactory() {
        List<String> offenders = Stream.concat(
                        matchingFiles("WebClient.builder()").stream(),
                        matchingFiles("WebClient.create(").stream())
                .filter(key -> !key.startsWith("com/kinlin/ai/config/WebClientConfig")
                        && !key.startsWith("com/kinlin/ai/infrastructure/http/"))
                .toList();

        assertTrue(offenders.isEmpty(), "WebClient construction outside transport owners: " + offenders);
    }

    @Test
    void upstreamEventStreamsAreOpenedOnlyByTheSseGateway() {
        List<String> offenders = Stream.concat(
                        matchingFiles("toEntityFlux(").stream(),
                        matchingFiles(".accept(MediaType.TEXT_EVENT_STREAM").stream())
                .filter(key -> !key.equals("com/kinlin/ai/gateway/AiSseGatewayService.java"))
                .toList();

        assertTrue(offenders.isEmpty(), "upstream SSE stream opened outside the SSE gateway: " + offenders);
    }

    @Test
    void agentOsUpstreamPathLiteralLivesOnlyInItsDefinition() {
        List<String> offenders = matchingFiles("/ai/agentos/v2").stream()
                .filter(key -> !key.equals("com/kinlin/ai/gateway/AgentOsPaths.java"))
                .toList();

        assertTrue(offenders.isEmpty(),
                "the AgentOS upstream root must be defined once (AgentOsPaths): " + offenders);
    }

    @Test
    void webSocketIsMarkedLegacyAndNeverCarriesAgentOsEvents() {
        List<String> webSocketFiles = matchingFiles("WebSocket");

        assertEquals(
                List.of("com/kinlin/ai/config/WebSocketConfig.java",
                        "com/kinlin/ai/controller/WebSocketController.java"),
                webSocketFiles,
                "unexpected WebSocket usage");

        for (String key : webSocketFiles) {
            assertTrue(SOURCES.get(key).contains("LEGACY"),
                    key + " must carry the LEGACY transport marker");
            assertFalse(SOURCES.get(key).toLowerCase().contains("agentos"),
                    key + " must not reference AgentOS events");
        }
    }

    @Test
    void noAcgSemanticsLiveInJavaPlatform() {
        List<String> offenders = matchingFiles("ACGLowering");

        assertTrue(offenders.isEmpty(), "ACG semantic implementation leaked into Java: " + offenders);
        assertTrue(Stream.of("acg", "scheduler", "topology")
                        .noneMatch(name -> Files.isDirectory(mainJava.resolve("com/kinlin/ai").resolve(name))),
                "ACG-semantic packages must not appear under com.kinlin.ai");
    }
}
