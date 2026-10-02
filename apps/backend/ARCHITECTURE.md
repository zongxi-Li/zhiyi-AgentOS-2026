# Java Backend 架构边界（J1.4D 冻结）

> 状态：J1.1 Backend Boundary Convergence + J1.2 Spring Boot Layering Convergence（含 J1.2B
> Controller / API Layering）+ J1.3 Legacy AI Cleanup + J1.4A/B/C/D Hardening 已落地。
> **本文档是 Java Backend 系统边界的权威表述**，由 `ArchitectureGuardTest`（30 条源码守卫）
> 与 GitHub Actions `backend-ci`（required gate）双机制强制。
> 后续阶段：N1.2 / N2 / N3（均为 contract evolution，见 §10/§14 准入门）。
>
> **J1.3 已移除**：legacy agent 整链（`AgentController` + `legacy/agent.AgentGatewayService`
> + `dto.agent.AgentChat*` + `agent.python.*` 配置，RestTemplate 随之全仓禁止）、
> WebSocket/STOMP/SockJS 传输（`WebSocketConfig`/`WebSocketController` +
> `spring-boot-starter-websocket`）、零引用配置键（`agent.trace-enabled`/`agent.federated.*`）、
> 未使用依赖（commons-io/commons-lang3）。正式网络栈 = Spring MVC inbound + WebClient outbound + SSE streaming。

## 1. Java Platform 职责边界

**Java Backend 只负责：**

| 职责 | 落点 |
|---|---|
| Authentication / Authorization | `security` / `filter`（JWT） |
| User / Role / Conversation | `service` + `repository` + `entity` |
| Platform persistence | Spring Data JPA / Hibernate / Flyway（冻结，禁改） |
| Public REST API | `controller` |
| AgentOS northbound typed contract | `dto.agentos` + `client.AgentOsClient`（N1.1 错误信封） |
| Java → Python client contracts | `client`（能力契约 + `PlatformAiClientException`） |
| Java → Python transport | `infrastructure.http`（platform-AI client 实现）+ `gateway`（AgentOS/proxy/SSE 家族） |
| SSE proxy | `AiSseGatewayService`（唯一 stream transport boundary，冻结至 N2） |
| multipart/file ingress | `controller` + `service` |
| platform-level rate limit | `interceptor` / `config` |
| observability | `observability` + 出站 metric hook |
| configuration | `config` / `infrastructure.http.PythonServiceProperties` |

**Java 不负责（出现即违例，守卫会拦截 ACG 语义包）：**

- TaskPlan semantics
- ACG topology
- ACGLowering
- Scheduler
- ExecutionBinding authority
- Semantic Patch
- Recovery policy
- Runtime graph mutation

## 2. 分层方向（J1.2 落地，守卫强制）

```
controller
    ↓
application/service        （业务编排 + fallback 决策；禁 transport token）
    ↓
client contract            （com.kinlin.ai.client；禁传输类型）
    ↓
client implementation      （infrastructure.http.WebClient*Client / gateway.AgentOsGatewayService）
    ↓
shared transport           （PythonClientFactory 统一 WebClient + PlatformAiTransport 统一超时/错误分类）
    ↓
Python
```

反向依赖（infrastructure/gateway → service/controller）由守卫拦截；业务 service 引用 `com.kinlin.ai.gateway` 一并拦截。

## 3. Java → Python 出站调用全景（J1.2 审计结论）

| caller 链 | client contract | client impl | endpoint family | 模式 | 超时来源 | 错误语义 | 分类 |
|---|---|---|---|---|---|---|---|
| ChatController → ChatService | `AiChatClient` | `WebClientAiChatClient` | `/ai/chat/text` | 同步 | `ai.service.timeout` | ChatService fallback（固定文案，J1.2 前移到应用层） | PLATFORM_AI |
| VoiceController → VoiceService | `AiChatClient` | `WebClientAiChatClient` | `/ai/chat/voice` | 同步 multipart | `ai.service.timeout` | 异常直传（VoiceController 500，行为不变） | PLATFORM_AI |
| VoiceController → VoiceService | `SpeechClient` | `WebClientSpeechClient` | `/ai/tts` | 同步 binary | `ai.service.timeout` | 异常直传（行为不变） | PLATFORM_AI |
| RagController / ChatService → RagService | `RagClient` | `WebClientRagClient` | `/rag/query`、`/rag/documents` | 同步 + multipart | `ai.service.timeout`（J1.2 补上，原先无显式超时） | query/list/delete：固定文案 fallback；upload：单一稳定前缀业务异常（J1.3 文案清理） | PLATFORM_AI |
| KnowledgeGraphController → KnowledgeGraphService | `KnowledgeGraphClient` | `WebClientKnowledgeGraphClient` | `/api/knowledge-graph/**` | 同步 | `ai.service.timeout` | error Map / 空 Map（信封解包在 client） | PLATFORM_AI |
| DigitalHumanController → DigitalHumanService | `DigitalHumanClient` | `WebClientDigitalHumanClient` | `/ai/digital-human/**` | 同步 + multipart | `ai.service.timeout` | 冻结措辞：404→"数字人不存在"、4xx/5xx→"AI服务返回错误: <status>"（J1.3 去实现细节泄漏） | PLATFORM_AI |
| EmotionController → EmotionAwareService | `EmotionClient` | `WebClientEmotionClient` | `/ai/emotion/**` | 同步 | `ai.service.timeout` | neutral 默认 / error Map | PLATFORM_AI |
| RoleFusionController → RoleFusionService | `RoleFusionClient` | `WebClientRoleFusionClient` | `/ai/role-fusion/**` | 同步 | `ai.service.timeout` | error Map | PLATFORM_AI |
| AgentOsMissionController / AgentOsRunController / AgentOsReviewController / AgentOsArtifactController / AgentOsObservationController（J1.2B 拆分，纯 gateway 投影） | `AgentOsClient` | `gateway.AgentOsGatewayService` | `/ai/agentos/v2/**`（missions/runs/materials/resources/attachments/…） | 同步/typed/multipart/binary | `agent.timeout-ms` / `progress` / `async-start`（按路径） | N1.1 AGENTOS_* 信封（返回值非异常） | AGENTOS_OFFICIAL |
| AgentOsEventController → AiSseGatewayService | （SSE 专用边界，无接口） | `AiSseGatewayService` | `/ai/agentos/v2/runs/{id}/events` | SSE | `ai.sse.idle-timeout-ms` / `max-duration-ms` | SSE error event（AI_STREAM_*） | AGENTOS_OFFICIAL |
| AiServiceProxyController → AiProxyService | （透传 transport，无业务接口） | `AiProxyService` | 任意 `/ai/**` | 同步 | `ai.service.timeout` | AI_UPSTREAM_* | PLATFORM_AI |
| AiServiceProxyController → AiSseGatewayService | （同上） | `AiSseGatewayService` | `/ai/chat/text/stream`、`/ai/test/sse` | SSE | `ai.sse.*` | AI_STREAM_* | PLATFORM_AI |
| HealthController → AiDependencyHealthClient | `AiDependencyHealthClient`（J1.2B 契约归位 `client`） | `WebClientAiDependencyHealthClient` | `/health/dependencies` | 同步 | `ai.service.health-timeout` | REACHABLE / DEGRADED | INFRASTRUCTURE |

~~AgentController → legacy.agent.AgentGatewayService（LEGACY_AI）~~ → **J1.3 整链删除**
（前端零调用、其余 Java 零调用、Python 侧本就无 `/ai/agent/{role}/chat` 路由；正式路径 =
AgentOS Mission/Run）。未保留任何 deprecated-but-active 或 compatibility fallback（开发期 hard cutover）。

UNKNOWN 分类：无（全部出站点已归类）。transport error ≠ business fallback：transport 层统一收敛为
`PlatformAiClientException`（TIMEOUT / UNAVAILABLE / REJECTED / UPSTREAM_ERROR / INVALID_RESPONSE，
携带 upstreamStatus），业务结果（fallback 文案、error Map、异常类型）由 application service 决定。
用户可见文案已去实现细节泄漏（J1.3：不再出现 Python/端口8000/内部端点；RAG 上传为单一
"文档上传失败: "前缀）；业务 fallback 触发条件一律未动。

## 4. Package layout（transport ownership）

```
com.kinlin.ai
├─ client/                          ← J1.2 新建：client 契约（能力接口 + 错误语义）
│  ├─ AiChatClient / SpeechClient / RagClient / KnowledgeGraphClient
│  ├─ DigitalHumanClient / EmotionClient / RoleFusionClient
│  ├─ AgentOsClient                 ← AgentOS northbound 契约（Controller 只依赖它）
│  ├─ AiDependencyHealthClient      ← J1.2B 迁入：健康探测契约
│  └─ PlatformAiClientException     ← transport error 稳定边界（type + upstreamStatus）
├─ infrastructure/http/            ← platform-AI client 实现 + 共享 transport（J1.1 建）
│  ├─ PythonServiceProperties / PythonClientFactory / TransportErrorClassifier
│  ├─ WebClientAiDependencyHealthClient   ← J1.2B 改名（实现归实现）
│  ├─ PlatformAiTransport           ← J1.2 新建：统一超时(ai.service.timeout)+错误分类
│  └─ WebClient*Client ×7           ← J1.2 新建：chat/speech/rag/KG/DH/emotion/roleFusion
├─ gateway/                        ← AgentOS/proxy/SSE transport family
│  ├─ AgentOsPaths                  ← 上游根路径 + 路径族工厂唯一定义（J1.2B 扩展）
│  ├─ AgentOsGatewayService         ← J1.2 迁入 gateway，implements AgentOsClient
│  ├─ AiSseGatewayService           ← 唯一上游 SSE 桥（idle/max 限流）
│  ├─ AiProxyService                ← /ai/** 白名单代理
│  └─ PythonServiceAuthentication / TrustedUserContextForwarder / AiGatewayHeaders / AiInternalServiceToken
├─ service/                        ← application services（编排 + fallback 决策；禁 transport）
└─ controller/                      ← REST 投影
   ├─ AgentOs{Mission,Run,Review,Artifact,Observation,Event}Controller  ← J1.2B 六分（ownership 冻结）
   └─ AgentOsControllerSupport     ← 共享状态投影（response/typedResponse，非业务）

~~legacy/agent/~~ → **J1.3 删除**；~~dto/agent/~~ → **J1.3 删除**（孤立 DTO）。
```

核心规则（守卫强制）：

1. 业务 Service 禁止一切 transport 操作（WebClient/RestTemplate/retrieve/exchangeToMono/bodyToMono/bodyValue/block/MultipartBodyBuilder/BodyInserters），禁止 import `com.kinlin.ai.gateway`。
2. `client` 契约包禁传输类型（reactor/web.reactive/org.springframework.http）。
3. `gateway`/`infrastructure` 禁止 import `service`/`controller`（方向守卫）。
4. Controller 禁止任何 transport（WebClient/RestTemplate/exchangeToMono/block）。
5. RestTemplate 全仓禁止（J1.3：legacy 边界已删除，任何生产源码出现 RestTemplate = 违例）。
6. `.clone().baseUrl(` / `WebClient.builder().baseUrl(` 只允许出现在 `PythonClientFactory`（唯一 owner）。
7. 上游 SSE 流只允许 `AiSseGatewayService` 打开。
8. `/ai/agentos/v2` 字面量只允许出现在 `AgentOsPaths` 定义处。
9. `PythonServiceProperties` 只允许 `infrastructure`/`gateway`/`config` 消费。
10. WebSocket/STOMP/SockJS = 已删除 transport（J1.3）：生产源码不得出现相关符号（守卫小写 token
    扫描强制）；流式一律 SSE（上游事件流仍只允许 `AiSseGatewayService`）。
11. J1.2B：AgentOS 北向路由 owner 冻结为六个 controller（守卫逐一核对文件名）；`AgentOsGatewayController` 保持删除态。
12. J1.2B：controller 禁 import `infrastructure`（实现）与 `repository`。
13. J1.2B：controller 禁为入站即剥除的身份头声明 `@RequestHeader`（X-User-Id/X-User-Role/X-Tenant-Id/X-Organization-Id/X-Workshop-Id/X-Internal-Service-Token/X-Authenticated-*）。

J1.2B Controller 层规则：controller 只做 web 层职责（参数绑定、HTTP 状态投影、认证上下文提取）；
上游路径族由 `AgentOsPaths` 工厂统一构建（controller 不持路径字面量，动作后缀留在唯一 owner）；
共享的仅是非业务状态投影 `AgentOsControllerSupport`（两个以上 controller 真实共用才提取）；
纯 gateway/projection endpoint 直连 `AgentOsClient` 契约（§2 分层第五层方向不变），SSE 直连
`AiSseGatewayService`，不套空 ApplicationService。

## 5. 配置 ownership（键名不变，值冻结）

| 键 | owner | 说明 |
|---|---|---|
| `ai.service.url` | `PythonServiceProperties` | **canonical Python root** |
| `ai.service.connect-timeout` | `PythonServiceProperties` | CONNECT |
| `ai.service.timeout` | `PythonServiceProperties` | platform-AI 家族统一 COMMAND/QUERY（J1.2 起经 `PlatformAiTransport` 对所有 capability client 生效，RAG 补上了缺失的显式超时） |
| `ai.service.health-timeout` | `PythonServiceProperties` | HEALTH_PROBE |
| `ai.sse.idle-timeout-ms` / `max-duration-ms` | `AiSseGatewayService` | STREAM_IDLE / STREAM_MAX |
| `agent.timeout-ms` | `AgentProperties` | AgentOS 家族 COMMAND/QUERY |
| `agent.progress-timeout-ms` | `AgentProperties` | AgentOS 轻查询/二进制/multipart |
| `agent.async-start-timeout-ms` | `AgentProperties` | ASYNC_START（POST /missions） |

~~`agent.python.*`（base-url + 4 个 role chat url）、`agent.trace-enabled`、`agent.federated.*`~~ →
**J1.3 删除**（legacy 链移除后零引用；`AgentProperties` 仅保留上表四个正式字段）。

双 timeout 键决策（J1.2 §17）：`ai.service.timeout` 与 `agent.timeout-ms` 数值当前相等但**语义独立保留**
（Platform-AI 生命周期 vs AgentOS 生命周期），不合并；运维调节需求一致确认后再收敛（J1.4 候选）。

部署兼容性：所有环境变量（`AI_SERVICE_URL` 等）与 docker compose 接线保持原样。

## 6. Trusted Header 边界（不变更协议）

| Header | 方向 | 处理 |
|---|---|---|
| `X-Internal-Service-Token` | Java→Python 生成 | `PythonServiceAuthentication`；入站被剥除 |
| `X-Authenticated-User-Id/Subject/Role/Tenant-Id` | Java→Python 生成 | `TrustedUserContextForwarder`；入站剥除 |
| `X-Trace-Id` | 入站可接受（严格校验）+ 出站转发 | `TraceIdFilter` + `TraceContext` |
| `X-User-Id` 等入站身份头 | 入站剥除 | `SensitiveIdentityHeaderFilter`（HIGHEST_PRECEDENCE） |
| `/ai/**` 代理转发头 | 双向白名单 | `AiProxyService` |

~~已知遗留：`AgentController` 死参数 `X-User-Id`~~ → **J1.2 已移除**；~~`ChatController`/
`VoiceController` 及全部 controller 同款死参数~~ → **J1.2B 已全部移除**
（7 个 controller 21 处；`StrippedIdentityHeaderBoundaryTest` 证明伪造头对落库/查询身份无影响，
守卫禁止该族头再以 `@RequestHeader` 复活）。

## 7. 测试与守卫

- `ArchitectureGuardTest`：§4 全部规则 + §2 方向守卫（J1.2 扩展：业务 service 禁 transport token、
  client 契约禁传输类型、transport 层禁反向 import、properties 消费面收敛）。
- `PlatformAiClientCharacterizationTest` + `FakePythonTransport`：platform-AI client 实现的真实
  序列化路径（method/URI/body 经默认 codecs）与 transport 错误分类（REJECTED/UPSTREAM_ERROR/TIMEOUT/UNAVAILABLE）。
- `RagServiceTest` / `ChatServiceTest` / `EmotionAwareServiceTest` / `RoleFusionServiceTest` /
  `KnowledgeGraphServiceTest` / `DigitalHumanServiceTest`：应用层 fallback 表征（固定文案逐字冻结）。
- `StrippedIdentityHeaderBoundaryTest`（J1.2B，覆盖
  Chat/Voice/Search/Conversation/Role/User/ChatQuality 七个 controller）：身份头死参数移除的行为一致性
  （~~`AgentControllerUserIdBoundaryTest`~~ 随 legacy `AgentController` 于 J1.3 整链删除）。
- `LegacyTransportRemovalTest`（J1.3）：`/ws` 与 `/api/agent/{role}/chat` 不再作为正式 endpoint（404）。
- `AgentOs{Mission,Run,Review,Artifact,Observation,Event}ControllerTest` + `AgentOsRouteCompatibilityTest`
  （J1.2B：六 controller 合体注册即证路由无冲突；旧 `AgentOsGatewayControllerTest` 迁移拆分）
  / `AgentOsGatewayServiceTest`（`gateway` 测试包）：N1.1 契约与 39 条路由冻结。
- `PythonClientFactoryTest` / `WebClientAiDependencyHealthClientTest` /
  `TransportErrorClassifierTest` / `AiProxyServiceTest` / `AiSseGatewayServiceTest`：既有契约继续钉住
  （~~`LegacyAgentGatewayServiceTest`~~ 随 legacy 链删除）。

## 8. J1.3 后遗留清单（明确不修，留给后续阶段）

1. `AiProxyService`/`AiSseGatewayService` 被 `AiServiceProxyController` 直接注入——二者是纯透传
   transport（无业务语义可抽契约），保留直连；若后续 proxy controller 需拆分再议。
2. `agent.timeout-ms` 与 `ai.service.timeout` 值相等但键分离——语义一致确认后合并（J1.4 候选）。
3. Python 侧 legacy role endpoints（`/ai/agent/{role}/chat`）：经审计**本就不存在**（`chat.py`
   仅有 `/ai/chat/*` 现代路由），无 residual 可清——§十五原则下本轮未动 Python。
4. KG/DH/Emotion/RoleFusion 的动态 Map projection 系统化 typed 化——N1.2。
5. SSE protocol（RuntimeEventEnvelope）——N2。
6. Resource transport（multipart/binary 上游传输的系统化收敛）——N3。
7. ~~GitHub 远端无 CI~~ → **J1.4D 已建立** `.github/workflows/backend-ci.yml`（required gate，
   push/PR → master 必跑 `mvn test` 全量含 Testcontainers + `mvn package -DskipTests`，见 §11）。

## 9. Architecture Freeze Status（J1.4D，2026-10-01）

**BACKEND ARCHITECTURE = FROZEN。**

冻结组件（任何修改必须满足 §10 准入门）：

| 组件 | 权威落点 |
|---|---|
| Controller ownership | AgentOS 北向六 controller 拆分 + 路由 owner（§4 规则 11~13） |
| 分层方向 | Controller → Application Service → Client Contract → Client Impl → Transport（§2，五层单向） |
| transport ownership | `PythonClientFactory` 唯一 WebClient 工厂；`PlatformAiTransport` 统一超时/错误分类；`AiProxyService` 唯一白名单代理 |
| SSE ownership | `AiSseGatewayService` 唯一上游 SSE 桥（冻结至 N2） |
| persistence authority | backend 启动期 Flyway 唯一 schema owner + Hibernate validate；OSIV=false；schema-tool=MANUAL_TOOL |
| cache authority | Spring Cache（生产 = RedisCacheManager `"roles"`，TTL 1h）唯一共享 cache owner；`@CacheEvict` 失效协议；Redis 故障 degrade-to-DB |
| JWT configuration authority | typed `JwtProperties`（HS512 ≥64B，启动期 fail-fast）；prod/compose 无默认 secret（`${APP_JWT_SECRET}` 缺失即启动失败） |
| network stack | Spring MVC inbound + WebClient outbound + SSE streaming（RestTemplate / WebSocket / STOMP / SockJS = 已删除态，守卫禁止复活） |
| Java 平台语义边界 | Java 不拥有 ACG semantics（TaskPlan / ACG topology / Scheduler / ExecutionBinding 等，§1） |

强制机制：`ArchitectureGuardTest`（30 条源码守卫，§7）+ `backend-ci` GitHub Actions required gate（§11）。

## 10. Freeze 准入门（未来修改的唯一合法理由）

**允许**（四类，须在 PR 描述附证据）：

| 类别 | 定义 | 证据要求 |
|---|---|---|
| `BUG_FIX` | 可复现缺陷，修复不改变边界 | 复现路径 + 回归测试 |
| `CONTRACT_EVOLUTION` | N1.2 Query Projection / N2 Runtime Event Protocol / N3 Resource Transport（§14） | 契约变更清单；不得破坏 §9 冻结组件 |
| `MEASURED_PERFORMANCE_DEFECT` | 有重复测量数据证明的性能缺陷 | 对照 §12 基线的 BEFORE/A/B 数据（同数据集/硬件/并发） |
| `SECURITY_FIX` | 有证据的安全缺陷 | 缺陷描述 + 修复后测试 |

**不接受**："为了更优雅"、"为了统一技术栈"、"为了以后可能需要"、无测量数据的"性能优化"。

## 11. CI Freeze Gate（`.github/workflows/backend-ci.yml`）

- **触发**：push → master、pull_request → master；**不做 path 过滤**（根级 pom/compose/.env 样例
  同样影响 backend，过滤省时风险不划算）。
- **Java 版本对齐**：CI = **17**（pom `java.version=17` + 运行镜像 `eclipse-temurin:17.0.19_10-jre-jammy`；
  本机 benchmark 的 JDK 21 只是测量工具，不代表项目版本）。
- **必跑两步**：`mvn test`（全量 305：unit + 30 条架构守卫 + PostgreSQL/Redis Testcontainers +
  security contracts + observability contracts，即 §十二~十四全部冻结门的执行体）+
  `mvn package -DskipTests`（生产 jar 可构建）。
- **性能基准不在 required gate**：`@Tag("performance")` 由 surefire `excludedGroups` 默认排除
  （`-Pperformance` 打开）；P50/P95/P99 基线永不作为 PR blocking threshold。
- **Testcontainers 1.21.4 override 是正式版本决策**：Boot 3.2.0 BOM 钉的 1.19.x 内置 docker-java
  无法对接 Docker Engine 29（API ≥1.44）；1.21.4（docker-java 3.4.2）向下兼容旧引擎，
  GitHub runner 的 Docker 直接可用。非临时本机 hack —— pom 属性注释 + 本节双记录，禁止回退。
- **分支保护建议**（不由工具自动改远端）：Settings → Branches → Add branch protection rule →
  勾选 Require status checks → 选中 `backend-gate`（job 名）为 required check（针对 master）。

## 12. Performance Baseline Registry（J1.4C，2026-09-30）

基线是**回归参照**，不是 SLA / 保证 / 容量上限；CI 不设性能阈值。

环境：Windows 11 本机 Docker Desktop（Engine 29.0.1）；benchmark JVM 21（仅测量工具）；
PostgreSQL 15.17-alpine + Redis 7.4.9-alpine（Testcontainers，pg-it/redis-it profiles）；
fake Python upstream（JDK HttpServer，15ms 固定延迟，**零真实 LLM/公网调用**，测的是 Java 自身开销）；
并发档 1/10/25/50，warmup 5s、measure 10s；指标 P50/P95/P99/max + 吞吐 + 错误率 + CPU +
Hikari pending + query/request + cache hitRatio。

| 负载 | 端点 | 吞吐 @50 | P50 @50 | 备注 |
|---|---|---|---|---|
| W1 auth-login | `POST /auth/login` | 315 rps | 154ms | BCrypt 故意成本，非缺陷 |
| W2 role-read | `GET /roles/{builtin}` | 10239 rps | 4ms | cache hitRatio=1.00 |
| W3 conversation-list | `GET /conversations` | —（饱和） | — | 50 并发 Hikari pending 峰值 27（§13 D2） |
| W4 chat-persistence | `POST /chat/text` | 1823 rps | 26ms | ≈4 statements/req；pending 峰值 9 |
| W5 agentos-gateway | `GET /api/agentos/v2/missions` | — | 17ms 恒定 | fake upstream 15ms + Java 开销 ≈2ms |

## 13. Known Debt Registry（J1.4A/B/C 汇总，冻结期只登记不修）

| # | 债务 | 事实 | 分类 |
|---|---|---|---|
| D1 | conversationList auto-title 写放大 | 列表查询夹带隐藏 auto-title UPDATE（20 会话 23 statements，J1.4C [DEBT-2]） | DEFERRED —— 需业务决策（列表是否继续自动命名） |
| D2 | conversation-list 50 并发 Hikari pending=27 | W3 饱和信号（W4 pending=9）；禁调 pool | DEFERRED —— 有测量证据后按 §10 准入 |
| D3 | AlertService 无界本地 alertHistory | `ConcurrentHashMap<String,List<Alert>>` 内存累积、无逐出（AlertService.java:28） | DEFERRED —— 需产品决策（接 metrics 后端或设上限） |
| D4 | `RoleSwitchOptimizer` 命名失真 | 名为 optimizer，实为 Spring Cache roles 权威 | ACCEPTED —— freeze 期禁大规模重命名 |
| D5 | Controller 直接暴露 Entity | 7 个 controller import `com.kinlin.ai.entity`（Chat/Auth/Role/Conversation/UserFeedback/Search/User） | DEFERRED —— 响应形状变更属 contract evolution（N1.2） |
| D6 | schema 无 FK 约束 | 贫血实体裸 UUID 列、无 relationship mapping | ACCEPTED —— schema 冻结；唯一性/CHECK/JSONB 已有真实 PG 契约测试 |
| D7 | 死持久化方法 | `ConversationRepository.findByUserIdAndRoleId`、`MessageRepository.findRecentMessages`、`UserFeedbackRepository.findByRoleId/findBySentiment/findByMessageId` 零生产调用（2026-10-01 grep 复核） | REMOVE —— 下阶段清理（含测试引用） |
| D8 | SSE 负载基准缺失 | W5 测的是 JSON 网关透传，SSE 流式未压测 | DEFERRED —— N2 改 SSE 协议后重建基准 |

## 14. N1.2 / N2 / N3 边界（contract evolution 通道）

后续三阶段全部走 §10 的 `CONTRACT_EVOLUTION` 通道：

- **N1.2 Query Projection**：KG/DH/Emotion/RoleFusion 动态 Map projection typed 化 + D5 Entity 暴露收敛。
- **N2 Runtime Event Protocol**：SSE protocol（RuntimeEventEnvelope）；`AiSseGatewayService` 所有权届时解冻。
- **N3 Resource Transport**：multipart/binary 上游传输系统化收敛。

三者允许修改相应边界，但**不得借机破坏**：五层分层（§2）、transport ownership（§4）、
ACG authority（Java 不拥有 ACG semantics，§1）。
