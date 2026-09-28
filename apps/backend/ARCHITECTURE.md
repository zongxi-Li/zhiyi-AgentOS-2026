# Java Backend 架构边界（J1.1 冻结）

> 状态：J1.1 Backend Boundary Convergence 已落地。
> 本文档是 Java Backend 系统边界的权威表述，由 `ArchitectureGuardTest` 以源码扫描方式强制。
> 后续阶段：J1.2 Spring Boot Layering → J1.3 Legacy AI Cleanup → J1.4 Backend Architecture Freeze → N1.2 / N2 / N3。

## 1. Java Platform 职责边界

**Java Backend 只负责：**

| 职责 | 落点 |
|---|---|
| Authentication / Authorization | `security` / `filter`（JWT） |
| User / Role / Conversation | `service` + `repository` + `entity` |
| Platform persistence | Spring Data JPA / Hibernate / Flyway（本轮冻结，禁改） |
| Public REST API | `controller` |
| AgentOS northbound typed contract | `dto.agentos` + `AgentOsGatewayService`（N1.1 错误信封） |
| Java → Python transport | `infrastructure.http` + `gateway` |
| SSE proxy | `AiSseGatewayService`（唯一 stream transport boundary） |
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

## 2. Java → Python 出站调用全景（J1.1 审计结论）

| caller | transport | endpoint family | 模式 | 超时来源 | 认证/头 | 错误映射 | 分类 |
|---|---|---|---|---|---|---|---|
| AgentOsGatewayController → AgentOsGatewayService | WebClient（统一 transport） | `/ai/agentos/v2/**`（missions/runs/materials/resources/…） | 同步 | `agent.timeout-ms` / `progress` / `async-start`（按路径） | 共享 filter：internal token + trace + user ctx | N1.1 AGENTOS_* 信封 | AGENTOS_OFFICIAL |
| AgentOsGatewayController → AiSseGatewayService | WebClient SSE | `/ai/agentos/v2/runs/{id}/events` | SSE | `ai.sse.idle-timeout-ms` / `max-duration-ms` | 同上 | SSE error event（AI_STREAM_*） | AGENTOS_OFFICIAL |
| AiServiceProxyController → AiProxyService（`/ai/**` 兜底代理） | WebClient | 任意 `/ai/**` | 同步 | `ai.service.timeout` | 共享 filter + 双向白名单 | AI_UPSTREAM_* | PLATFORM_AI |
| AiServiceProxyController → AiSseGatewayService | WebClient SSE | `/ai/chat/text/stream`、`/ai/test/sse` | SSE | `ai.sse.*` | 共享 filter + TrustedUserContextForwarder | AI_STREAM_* | PLATFORM_AI |
| ChatService → AiService | WebClient | `/ai/chat/text` | 同步 | `ai.service.timeout` | 共享 filter | 静默 fallback ChatResponse | PLATFORM_AI |
| AiService（voice/tts） | WebClient | `/ai/chat/voice`、`/ai/tts` | 同步 | `ai.service.timeout` | 共享 filter | 无映射/泄漏 | PLATFORM_AI |
| RagService | WebClient | `/rag/query`、`/rag/documents` | 同步 | 无显式（仅 connect 15s） | 共享 filter | fallback + e.getMessage() 泄漏 | PLATFORM_AI |
| KnowledgeGraphService | WebClient | `/api/knowledge-graph/**` | 同步 | `ai.service.timeout` | 共享 filter | 吞错返回空 Map | PLATFORM_AI |
| DigitalHumanService | WebClient | `/ai/digital-human/**` | 同步 | `ai.service.timeout` | 共享 filter | fallback + 泄漏 | PLATFORM_AI |
| EmotionAwareService | WebClient | `/ai/emotion/**` | 同步 | `ai.service.timeout` | 共享 filter | 吞错返回空 Map | PLATFORM_AI |
| RoleFusionService | WebClient | `/ai/role-fusion/**` | 同步 | `ai.service.timeout` | 共享 filter | 吞错返回空 Map | PLATFORM_AI |
| VoiceService → AiService | （委托） | voice/tts | 同步 | 继承 AiService | 继承 | 继承 | PLATFORM_AI |
| AgentController → legacy.agent.AgentGatewayService | **RestTemplate（legacy 隔离，不迁移）** | `agent.python.{role}-chat-url`（缺省 `base-url + /ai/agent/{role}/chat`） | 同步 | `agent.timeout-ms`（connect+read） | 拦截器：internal token + user ctx（新建头） | failure + 原样上游 body（legacy 语义冻结） | LEGACY_AI |
| HealthController → AiDependencyHealthClient | WebClient | `/health/dependencies` | 同步 | `ai.service.health-timeout`（默认 3000，原硬编码 3s） | 共享 filter（/health 跳过 user ctx） | REACHABLE / DEGRADED | INFRASTRUCTURE |

UNKNOWN 分类：无（全部出站点已归类）。除上述外无其他出站传输（无 RestClient/HttpClient/URLConnection/裸 URL）。

## 3. Client families（transport ownership）

```
com.kinlin.ai
├─ infrastructure/http/            ← transport 唯一 owner（J1.1 新建）
│  ├─ PythonServiceProperties      ← canonical 配置 owner（ai.service.*）
│  ├─ PythonClientFactory          ← 唯一 baseUrl 接线点 + metric endpoint family
│  ├─ TransportErrorClassifier     ← transport 级错误分类（timeout/connection）
│  └─ AiDependencyHealthClient     ← INFRASTRUCTURE 健康探针
├─ gateway/                        ← AgentOS/proxy/SSE transport family
│  ├─ AgentOsPaths                 ← 上游根路径唯一定义
│  ├─ AgentOsGatewayService        ← AGENTOS_OFFICIAL 同步/typed/multipart
│  ├─ AiSseGatewayService          ← 唯一上游 SSE 桥（idle/max 限流）
│  ├─ AiProxyService               ← /ai/** 白名单代理
│  └─ PythonServiceAuthentication / TrustedUserContextForwarder / AiGatewayHeaders / AiInternalServiceToken
├─ legacy/agent/                   ← LEGACY_AI 隔离区（J1.3 删除）
│  └─ AgentGatewayService          ← 唯一 RestTemplate（表征测试已冻结行为）
└─ service/                        ← 业务 service 持有 endpoint + 错误语义
```

transport 归属的精确表述：业务 Service 不再拥有 **transport 构造/配置 authority**（WebClient 构造、base URL、auth filter、connect timeout 全部收归 `infrastructure.http` / 共享 builder），但平台 AI 家族仍**通过共享 transport 直接执行 HTTP 调用**（endpoint path、retrieve、timeout application、fallback 语义由各 service 自持）。Client/Application 分层（`Application Service → PlatformAiClient → WebClient`）是 J1.2 的第一优先级，J1.1 不做。

核心规则（守卫强制）：

1. 业务 Service 不创建 WebClient/RestTemplate、不拼 base URL、不读 `ai.service.*` 配置。
2. `.baseUrl(` 只允许出现在 `PythonClientFactory`（唯一 owner，机器可证明；测试缝隙同样禁止自行接线）。
3. Controller 禁止任何 transport（WebClient/RestTemplate/exchangeToMono/block）。
4. RestTemplate 只允许存在于 `legacy/agent`；正式代码新增 RestTemplate = 违例。
5. 上游 SSE 流只允许 `AiSseGatewayService` 打开。
6. `/ai/agentos/v2` 字面量只允许出现在 `AgentOsPaths` 定义处。
7. WebSocket/STOMP = LEGACY transport，禁止承载 AgentOS 事件流；删除留给 J1.3。

## 4. 配置 ownership（J1.1 收敛，键名不变）

| 键 | owner | 说明 |
|---|---|---|
| `ai.service.url` | `PythonServiceProperties` | **canonical Python root**（所有正式 client 经 factory 取用） |
| `ai.service.connect-timeout` | `PythonServiceProperties` | CONNECT |
| `ai.service.timeout` | `PythonServiceProperties` | platform-ai 家族 COMMAND/QUERY |
| `ai.service.health-timeout` | `PythonServiceProperties` | HEALTH_PROBE（新增键，默认 3000 = 原硬编码值；`AI_SERVICE_HEALTH_TIMEOUT` 可覆盖） |
| `ai.sse.idle-timeout-ms` / `max-duration-ms` | `AiSseGatewayService` | STREAM_IDLE / STREAM_MAX |
| `agent.timeout-ms` | `AgentProperties` | AgentOS 家族 COMMAND/QUERY + legacy role chat（值 240000 与 ai.service.timeout 当前相等，未合并，值冻结） |
| `agent.progress-timeout-ms` | `AgentProperties` | AgentOS 轻查询/二进制/multipart |
| `agent.async-start-timeout-ms` | `AgentProperties` | ASYNC_START（POST /missions） |
| `agent.python.base-url` | `AgentProperties` | **legacy alias**：仅 legacy role chat 使用；与 `ai.service.url` 同接 `AI_SERVICE_URL` 环境变量，部署无需改动 |
| `agent.python.{role}-chat-url` | `AgentProperties` | legacy 覆盖项，仅 legacy scope |

部署兼容性：所有环境变量（`AI_SERVICE_URL` 等）与 docker compose 接线保持原样。

## 5. Trusted Header 边界（不变更协议，仅收敛 ownership）

| Header | 方向 | 处理 |
|---|---|---|
| `X-Internal-Service-Token` | Java→Python 生成 | `PythonServiceAuthentication`（共享 filter）；入站被 `SensitiveIdentityHeaderFilter` 剥除 |
| `X-Authenticated-User-Id/Subject/Role/Tenant-Id` | Java→Python 生成 | `TrustedUserContextForwarder`（自 Spring Security 重建）；入站剥除（J1.1 扩入黑名单） |
| `X-Trace-Id` | 入站可接受（严格校验 32-hex/UUID，非法即重生成）+ 出站转发 | `TraceIdFilter` + `TraceContext` |
| `X-User-Id` 等入站身份头 | 入站剥除 | `SensitiveIdentityHeaderFilter`（HIGHEST_PRECEDENCE） |
| `/ai/**` 代理转发头 | 双向白名单 | `AiProxyService`（入站仅 content-type/accept/accept-language/user-agent；出站仅 content-type/content-disposition/cache-control） |

已知遗留（记录，不在 J1.1 处理）：`AgentController` 仍声明 `@RequestHeader("X-User-Id")` 参数，但该头入站即被剥除，参数恒为 null（死参数，J1.2/清理时移除）。

## 6. Observability（§18 基础）

- 出站 WebClient：共享 filter 统一记录 `kinlin.python.outbound.requests`（tags: family/outcome/status）与 `kinlin.python.outbound.duration`（tags: family/outcome），经 actuator/prometheus 暴露。family 取低基数路径前缀（agentos/legacy_agent/platform_*/health/other）。
- 出站 RestTemplate（legacy）：`AgentGatewayService` 拦截器内同名计数（family=legacy_agent）。
- 不含 dashboard/alert/Prometheus 部署（Performance Phase 范围）。

## 7. 测试与守卫

- `ArchitectureGuardTest`：§3 全部规则的源码扫描守卫。
- `LegacyAgentGatewayServiceTest`：legacy 链表征测试（端点解析/头部/错误语义冻结）。
- `PythonClientFactoryTest` / `AiDependencyHealthClientTest` / `TransportErrorClassifierTest`：transport 归属与行为表征。
- 存量：`AgentOsGatewayControllerTest` / `AgentOsGatewayServiceTest` / `AiProxyServiceTest` / `AiSseGatewayServiceTest` / `SensitiveIdentityHeaderFilterTest` / `HealthControllerTest` 等继续钉住既有契约。

## 8. J1.1 遗留清单（明确不修，留给后续阶段）

1. 业务 Service 仍直接执行平台 AI HTTP 调用（endpoint/retrieve/timeout application/fallback 自持）——**J1.2 第一优先级**：引入 `PlatformAiClient` 家族分层（Application Service → Typed Client → Transport）。
2. 平台 AI 家族错误语义不统一（fallback/吞错/泄漏三种并存）——J1.2 统一 transport error mapping。
3. `agent.timeout-ms` 与 `ai.service.timeout` 值相等但键分离——J1.2 配置合并候选。
4. `RagService` 无显式请求超时——J1.2 补 QUERY 类超时。
5. `AgentController` 死参数 `X-User-Id`——J1.2 移除。
6. `AiService`/`RagService` 中文 fallback 文案含部署细节（端口 8000）——J1.3/产品定夺。
7. WebSocket/STOMP 删除、legacy role endpoints 删除——J1.3。
8. `mapper` 空包删除——J1.2 结构清理。
9. SSE protocol（RuntimeEventEnvelope）——N2。
10. GitHub 远端无 CI（`.github/workflows` 为空，185 测试与架构守卫仅本地强制）——J1.4 Architecture Freeze 前必须补 GitHub Actions 跑 `mvn test`（含 ArchitectureGuardTest）。
