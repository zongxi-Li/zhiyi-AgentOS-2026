# Java Backend 架构边界（J1.3 冻结）

> 状态：J1.1 Backend Boundary Convergence + J1.2 Spring Boot Layering Convergence（含 J1.2B
> Controller / API Layering）+ J1.3 Legacy AI Cleanup 已落地。本文档是 Java Backend 系统边界的权威表述，由
> `ArchitectureGuardTest` 以源码扫描方式强制。
> 后续阶段：J1.4 Backend Architecture Freeze → N1.2 / N2 / N3。
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
7. GitHub 远端无 CI（`.github/workflows` 为空，测试与架构守卫仅本地强制）——J1.4 前必须补 GitHub Actions 跑 `mvn test`。
