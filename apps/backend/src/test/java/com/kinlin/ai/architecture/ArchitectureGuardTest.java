package com.kinlin.ai.architecture;

import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.core.annotation.AnnotatedElementUtils;
import org.springframework.transaction.annotation.Transactional;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;
import java.util.stream.Stream;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

/**
 * Architecture guards for the J1.1 backend boundary convergence and the J1.2
 * Spring Boot layering convergence.
 *
 * <p>Source-level guards (no bytecode analysis dependency). They enforce the decisions
 * frozen in {@code apps/backend/ARCHITECTURE.md}:</p>
 *
 * <ul>
 *   <li>Controllers never operate transport (WebClient / RestTemplate).</li>
 *   <li>J1.3: RestTemplate is forbidden outright; the legacy agent boundary no longer
 *       exists.</li>
 *   <li>The Python root and {@code ai.service.*} / {@code agent.*} property placeholders
 *       are resolved only by the infrastructure transport owner; SSE timeouts only by
 *       the SSE gateway.</li>
 *   <li>Business services never wire a base URL or construct an HTTP client; base-URL
 *       wiring belongs solely to {@code PythonClientFactory}, test seams included.</li>
 *   <li>J1.2: business services operate no transport at all — endpoint paths,
 *       serialization, timeouts and transport error handling live in client
 *       implementations ({@code infrastructure.http}, {@code gateway}); services call
 *       {@code com.kinlin.ai.client} contracts only.</li>
 *   <li>J1.2: client contracts are transport-free; client implementations and gateway
 *       transports never import application services or controllers.</li>
 *   <li>J1.2B: the AgentOS northbound is owned by exactly six frozen controllers; web
 *       controllers import no infrastructure implementation, no repository, and declare
 *       no {@code @RequestHeader} for the identity headers stripped inbound.</li>
 *   <li>The AgentOS upstream path is reachable only through the single AgentOS
 *       transport family.</li>
 *   <li>J1.3: WebSocket / STOMP / SockJS are removed transports — production sources
 *       must not reference them at all; streaming is SSE-only.</li>
 *   <li>J1.4B: no JWT default secret in prod/compose configs; JwtUtil reads no
 *       {@code @Value}; RoleSwitchOptimizer carries no local mutable role cache;
 *       controllers/services never touch cache infrastructure directly.</li>
 *   <li>J1.4A: controllers declare no {@code @Transactional}; formal configs
 *       (canonical/prod/compose) pin ddl-auto=validate + open-in-view=false and never
 *       point at H2; MyBatis / MyBatis-Plus stay banned at dependency and import level.</li>
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

    /** Transport markers that only client implementations / gateway transports may carry. */
    private static final List<String> TRANSPORT_OPERATION_TOKENS = List.of(
            "WebClient",
            "RestTemplate",
            "MultipartBodyBuilder",
            "BodyInserters",
            ".retrieve(",
            ".exchangeToMono(",
            ".bodyToMono(",
            ".bodyValue(",
            ".block("
    );

    /** J1.2: application services own orchestration and fallback decisions — never transport. */
    @Test
    void businessServicesOperateNoTransport() {
        List<String> offenders = filesUnder("com/kinlin/ai/service/").stream()
                .filter(key -> {
                    String content = SOURCES.get(key);
                    return TRANSPORT_OPERATION_TOKENS.stream().anyMatch(content::contains)
                            || content.contains("com.kinlin.ai.gateway");
                })
                .toList();

        assertTrue(offenders.isEmpty(),
                "business services must not operate transport or import the gateway family: " + offenders);
    }

    /** J1.2: client contracts describe capabilities — never transport types. */
    @Test
    void clientContractsStayTransportFree() {
        List<String> offenders = filesUnder("com/kinlin/ai/client/").stream()
                .filter(key -> {
                    String content = SOURCES.get(key);
                    return content.contains("org.springframework.web.reactive")
                            || content.contains("reactor.core")
                            || content.contains("org.springframework.http")
                            || content.contains(".block(")
                            || content.contains(".retrieve(");
                })
                .toList();

        assertTrue(offenders.isEmpty(), "client contracts must stay transport-free: " + offenders);
    }

    /** J1.2: dependency direction — transport implementations never look up into app/controller layers. */
    @Test
    void transportLayersNeverImportApplicationOrWebLayers() {
        List<String> offenders = Stream.concat(
                        filesUnder("com/kinlin/ai/gateway/").stream(),
                        filesUnder("com/kinlin/ai/infrastructure/").stream())
                .filter(key -> {
                    String content = SOURCES.get(key);
                    return content.contains("import com.kinlin.ai.service")
                            || content.contains("import com.kinlin.ai.controller");
                })
                .toList();

        assertTrue(offenders.isEmpty(),
                "transport implementations must not import application/controller classes: " + offenders);
    }

    /** J1.2: the canonical Python properties are consumed only by the transport families and config wiring. */
    @Test
    void pythonServicePropertiesAreConsumedOnlyByTransportAndConfig() {
        List<String> offenders = matchingFiles("import com.kinlin.ai.infrastructure.http.PythonServiceProperties")
                .stream()
                .filter(key -> !key.startsWith("com/kinlin/ai/infrastructure/")
                        && !key.startsWith("com/kinlin/ai/gateway/")
                        && !key.startsWith("com/kinlin/ai/config/"))
                .toList();

        assertTrue(offenders.isEmpty(),
                "PythonServiceProperties must only be consumed by transport families and config: " + offenders);
    }

    /** J1.2B: AgentOS northbound ownership is frozen on the six split controllers. */
    @Test
    void agentOsRoutesHaveFrozenOwnershipControllers() {
        List<String> owners = filesUnder("com/kinlin/ai/controller/").stream()
                .filter(key -> SOURCES.get(key).contains("RequestMapping(\"/api/agentos/v2\")"))
                .sorted()
                .toList();

        assertEquals(
                List.of(
                        "com/kinlin/ai/controller/AgentOsArtifactController.java",
                        "com/kinlin/ai/controller/AgentOsEventController.java",
                        "com/kinlin/ai/controller/AgentOsMissionController.java",
                        "com/kinlin/ai/controller/AgentOsObservationController.java",
                        "com/kinlin/ai/controller/AgentOsReviewController.java",
                        "com/kinlin/ai/controller/AgentOsRunController.java"),
                owners,
                "AgentOS controller ownership must stay frozen (J1.2B)");

        assertTrue(matchingFiles("AgentOsGatewayController").isEmpty(),
                "the aggregated AgentOsGatewayController must stay deleted");
    }

    /** J1.2B: controllers import no infrastructure implementation and no persistence repository. */
    @Test
    void controllersNeverImportInfrastructureImplementationsOrRepositories() {
        List<String> offenders = filesUnder("com/kinlin/ai/controller/").stream()
                .filter(key -> {
                    String content = SOURCES.get(key);
                    return content.contains("import com.kinlin.ai.infrastructure")
                            || content.contains("import com.kinlin.ai.repository");
                })
                .toList();

        assertTrue(offenders.isEmpty(),
                "controllers must not import infrastructure implementations or repositories: " + offenders);
    }

    /** J1.2B: headers stripped by SensitiveIdentityHeaderFilter can never re-enter as @RequestHeader. */
    @Test
    void controllersDeclareNoStrippedIdentityHeaderParameters() {
        List<String> stripped = List.of(
                "x-user-id",
                "x-user-role",
                "x-tenant-id",
                "x-organization-id",
                "x-workshop-id",
                "x-internal-service-token",
                "x-authenticated-user-id",
                "x-authenticated-user-subject",
                "x-authenticated-user-role",
                "x-authenticated-tenant-id");

        List<String> offenders = filesUnder("com/kinlin/ai/controller/").stream()
                .filter(key -> {
                    String content = SOURCES.get(key).toLowerCase();
                    return content.contains("@requestheader") && stripped.stream()
                            .anyMatch(header -> content.contains("\"" + header + "\""));
                })
                .toList();

        assertTrue(offenders.isEmpty(),
                "controllers must not declare @RequestHeader for stripped identity headers: " + offenders);
    }

    /** J1.3: the legacy agent boundary is gone — RestTemplate must not appear anywhere in production sources. */
    @Test
    void restTemplateIsForbidden() {
        List<String> offenders = matchingFiles("RestTemplate");

        assertTrue(offenders.isEmpty(), "RestTemplate must not appear in production sources: " + offenders);
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
    void baseUrlWiringHappensOnlyInTheClientFactory() {
        List<String> offenders = Stream.of(".clone().baseUrl(", "WebClient.builder().baseUrl(")
                .flatMap(needle -> matchingFiles(needle).stream())
                .distinct()
                .filter(key -> !key.equals("com/kinlin/ai/infrastructure/http/PythonClientFactory.java"))
                .toList();

        assertTrue(offenders.isEmpty(),
                "base-URL wiring must happen only in PythonClientFactory (sole owner): " + offenders);
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

    /** J1.3: WebSocket/STOMP/SockJS are removed transports — no production source may reference them. */
    @Test
    void webSocketStompAndSockjsAreForbidden() {
        List<String> forbiddenTokens = List.of(
                "websocket",
                "stomp",
                "sockjs",
                "@messagemapping",
                "simplmessagingtemplate");

        List<String> offenders = SOURCES.entrySet().stream()
                .filter(entry -> {
                    String content = entry.getValue().toLowerCase();
                    return forbiddenTokens.stream().anyMatch(content::contains);
                })
                .map(Map.Entry::getKey)
                .sorted()
                .toList();

        assertTrue(offenders.isEmpty(),
                "WebSocket/STOMP/SockJS are removed transports (SSE-only): " + offenders);
    }

    /**
     * Authority symbols of the Python-owned ACG/execution semantics. Banning the symbol
     * (class/type name), never the bare concept word: e.g. {@code TaskPlan} stays legal
     * because a future query projection may surface it as a display field, while a Java
     * {@code TaskPlanPatch} implementation would be an authority violation.
     */
    private static final List<String> ACG_AUTHORITY_SYMBOLS = List.of(
            "ACGLowering",
            "ACGLowerer",
            "ACGLoweringInput",
            "TaskPlanPatch",
            "CompiledACGPackage",
            "BindingManifest",
            "CapabilityBindingSolver",
            "SemanticGraphPatchService"
    );

    @Test
    void noAcgSemanticsLiveInJavaPlatform() {
        List<String> offenders = ACG_AUTHORITY_SYMBOLS.stream()
                .flatMap(symbol -> matchingFiles(symbol).stream().map(file -> file + " contains " + symbol))
                .toList();

        assertTrue(offenders.isEmpty(), "ACG semantic implementation leaked into Java: " + offenders);
        assertTrue(Stream.of("acg", "scheduler", "topology")
                        .noneMatch(name -> Files.isDirectory(mainJava.resolve("com/kinlin/ai").resolve(name))),
                "ACG-semantic packages must not appear under com.kinlin.ai");
    }

    // ------------------------------------------------------------------
    // J1.4A persistence guards
    // ------------------------------------------------------------------

    /** J1.4A §十七B：Controller 不得声明 @Transactional（含组合注解，反射级检查，不受注释误伤）。 */
    @Test
    void controllersDeclareNoTransactional() throws Exception {
        List<String> offenders = new java.util.ArrayList<>();
        try (Stream<Path> paths = Files.list(mainJava.resolve("com/kinlin/ai/controller"))) {
            for (Path file : paths.filter(p -> p.toString().endsWith(".java")).toList()) {
                String className = "com.kinlin.ai.controller."
                        + file.getFileName().toString().replaceFirst("\\.java$", "");
                Class<?> clazz = Class.forName(className);
                if (AnnotatedElementUtils.hasAnnotation(clazz, Transactional.class)) {
                    offenders.add(className);
                }
            }
        }

        assertTrue(offenders.isEmpty(), "controllers must not declare @Transactional: " + offenders);
    }

    /** 正式（production-authority）配置文件集合；dev/test 属开发豁免面，不在其列。 */
    private static final List<String> FORMAL_CONFIGS = List.of(
            "src/main/resources/application.yml",
            "src/main/resources/application-prod.yml",
            "src/main/resources/application-compose.yml");

    /** J1.4B：production-authority 配置（不含 canonical——canonical 带开发默认属 dev 继承路径）。 */
    private static final List<String> FORMAL_PROD_CONFIGS = List.of(
            "src/main/resources/application-prod.yml",
            "src/main/resources/application-compose.yml");

    private static String formalConfig(String relativePath) {
        try {
            return Files.readString(Path.of(relativePath));
        } catch (IOException e) {
            throw new IllegalStateException("无法读取正式配置文件: " + relativePath, e);
        }
    }

    private static final Pattern DDL_AUTO_PATTERN = Pattern.compile("ddl-auto:\\s*(\\S+)");

    /** J1.4A §十七C：正式配置禁止 update/create/create-drop；Hibernate 只有 validate 权。 */
    @Test
    void formalConfigsAllowOnlyValidateSchemaTool() {
        List<String> offenders = FORMAL_CONFIGS.stream()
                .flatMap(path -> DDL_AUTO_PATTERN.matcher(formalConfig(path)).results()
                        .map(matcher -> path + " -> ddl-auto: " + matcher.group(1)))
                .filter(match -> !match.endsWith("validate"))
                .toList();

        assertTrue(offenders.isEmpty(),
                "formal configs must use ddl-auto=validate only (Flyway owns mutation): " + offenders);
    }

    /** J1.4A §十七C：canonical 必须显式声明 validate（默认值漂移防线）。 */
    @Test
    void canonicalConfigDeclaresValidateExplicitly() {
        String canonical = formalConfig("src/main/resources/application.yml");
        assertTrue(DDL_AUTO_PATTERN.matcher(canonical).results()
                        .anyMatch(match -> match.group(1).equals("validate")),
                "canonical application.yml must declare ddl-auto: validate explicitly");
    }

    /** J1.4A §十七D：canonical 必须显式 open-in-view: false；正式配置不得改回 true。 */
    @Test
    void osivStaysExplicitlyClosedInFormalConfigs() {
        String canonical = formalConfig("src/main/resources/application.yml");
        assertTrue(canonical.contains("open-in-view: false"),
                "canonical application.yml must declare open-in-view: false explicitly");

        List<String> offenders = FORMAL_CONFIGS.stream()
                .filter(path -> formalConfig(path).contains("open-in-view: true"))
                .toList();
        assertTrue(offenders.isEmpty(), "OSIV must never be re-enabled in formal configs: " + offenders);
    }

    /** J1.4A §十七E：正式配置的 datasource 不得指向 H2（H2 仅限 dev/test 快速测试面）。 */
    @Test
    void formalConfigsNeverPointAtH2() {
        List<String> offenders = FORMAL_CONFIGS.stream()
                .filter(path -> {
                    String content = formalConfig(path);
                    return content.contains("org.h2.Driver") || content.contains("jdbc:h2:");
                })
                .toList();

        assertTrue(offenders.isEmpty(), "formal configs must not use H2 datasource: " + offenders);
    }

    /** J1.4A §十七F：MyBatis / MyBatis-Plus 禁止回归——依赖与 import 双关卡。 */
    @Test
    void myBatisStaysBanned() throws IOException {
        String pom = Files.readString(Path.of("pom.xml"));
        assertTrue(Pattern.compile("<artifactId>\\s*mybatis").matcher(pom).results().count() == 0,
                "pom.xml must not declare MyBatis / MyBatis-Plus dependencies");

        // import 行级检查：剥掉注释行，避免文档误伤
        Pattern importPattern = Pattern.compile("^import\\s+(?:static\\s+)?(?:org\\.mybatis|org\\.apache\\.ibatis)");
        List<String> offenders = SOURCES.entrySet().stream()
                .filter(entry -> entry.getValue().lines()
                        .map(String::trim)
                        .filter(line -> !line.isEmpty() && !line.startsWith("//")
                                && !line.startsWith("*") && !line.startsWith("/*"))
                        .anyMatch(line -> importPattern.matcher(line).find()))
                .map(Map.Entry::getKey)
                .toList();

        assertTrue(offenders.isEmpty(), "MyBatis imports are banned in production sources: " + offenders);
    }

    // ------------------------------------------------------------------
    // J1.4B infrastructure guards
    // ------------------------------------------------------------------

    /** J1.4B §十九A：prod/compose 配置不得携带 JWT 默认 secret（fail-closed 占位符须无默认值）。 */
    @Test
    void productionJwtSecretPlaceholderHasNoFallback() {
        List<String> offenders = FORMAL_PROD_CONFIGS.stream()
                .filter(path -> {
                    String content = formalConfig(path);
                    // secret 行必须是无默认值的 ${APP_JWT_SECRET}；出现 ":-" 即仓库默认回退
                    return !content.contains("secret: ${APP_JWT_SECRET}")
                            || content.contains("secret: ${APP_JWT_SECRET:");
                })
                .toList();

        assertTrue(offenders.isEmpty(),
                "prod/compose must declare app.jwt.secret as ${APP_JWT_SECRET} with no fallback: " + offenders);
    }

    /** J1.4B §十九B：secret/expiration 归 JwtProperties 持有，JwtUtil 不得直接 @Value。 */
    @Test
    void jwtUtilDoesNotReadConfigValuesDirectly() {
        String jwtUtil = SOURCES.get("com/kinlin/ai/util/JwtUtil.java");
        if (jwtUtil == null) {
            throw new IllegalStateException("JwtUtil must stay at com/kinlin/ai/util/JwtUtil.java");
        }
        // 带括号精确匹配注解使用，避免 javadoc 散文（"不再直接 @Value"）误伤
        assertFalse(jwtUtil.contains("@Value("),
                "JwtUtil must take secret/expiration from typed JwtProperties, not @Value");
    }

    /** J1.4B §十九C：Role 缓存权威唯一——不得重新引入第二个 mutable 本地 Role 缓存。 */
    @Test
    void roleSwitchOptimizerStaysFreeOfLocalMutableRoleCache() {
        String optimizer = SOURCES.get("com/kinlin/ai/service/RoleSwitchOptimizer.java");
        if (optimizer == null) {
            throw new IllegalStateException(
                    "RoleSwitchOptimizer must stay at com/kinlin/ai/service/RoleSwitchOptimizer.java");
        }
        assertFalse(optimizer.contains("ConcurrentHashMap"),
                "a second mutable local Role cache must not reappear (Spring Cache is the sole authority)");
        // 方法定义形状精确匹配（void + 括号），避免 javadoc 提及历史方法名时误伤
        Pattern localEvictMethod = Pattern.compile("void\\s+clear(?:Role|All)Cache\\s*\\(");
        assertFalse(localEvictMethod.matcher(optimizer).find(),
                "local cache eviction methods must not reappear; use @CacheEvict on write paths");
    }

    /** J1.4B §十九D：Controller 不得操作缓存基础设施（含手工清缓存的 @CacheEvict）。 */
    @Test
    void controllersOperateNoCacheInfrastructure() {
        List<String> offenders = filesUnder("com/kinlin/ai/controller/").stream()
                .filter(key -> {
                    String content = SOURCES.get(key);
                    return content.contains("CacheManager") || content.contains("RedisTemplate")
                            || content.contains("@CacheEvict") || content.contains("@CachePut");
                })
                .toList();

        assertTrue(offenders.isEmpty(),
                "controllers must not touch cache infrastructure; eviction belongs to services: " + offenders);
    }

    /** J1.4B §十九E：业务 service 不得直连 RedisTemplate（缓存只走 Spring Cache 抽象）。 */
    @Test
    void businessServicesOperateNoRedisTemplate() {
        List<String> offenders = filesUnder("com/kinlin/ai/service/").stream()
                .filter(key -> SOURCES.get(key).contains("RedisTemplate"))
                .toList();

        assertTrue(offenders.isEmpty(),
                "business services must use the Spring Cache abstraction, never RedisTemplate: " + offenders);
    }
}
