# Planner Runtime Streaming P0 总体验收收敛

- 日期：2026-09-03
- 当前 HEAD：`98640facf6f4c32b3992ad77d320af4a07fe8f63`
- 依据：重新核对当前源码、测试、容器运行态和浏览器入口；不把此前实施报告当作事实依据。
- 范围：只收敛 Planner Runtime Streaming P0，不进入 Content Plane、Control Plane，不新增第二套 RuntimeEvent/Broker/SSE，不把旧 `AcgVisualizationView` 提升为正式入口。

## Baseline

本轮开始时工作区只有此前审计文件未跟踪，HEAD 与 `origin/master` 一致。审计结论为 Runtime Streaming 处于 BROKEN/PARTIAL：Java RuntimeEvent SSE 代理缺失、原生生产流存在静默同步回退风险、正式 Workspace 消费链路未闭合、重试 attempt 隔离和取消语义不完整。

本轮实现后的代码链路已补齐，但正式验收仍受两项事实限制：没有可用的登录态/授权凭据，不能伪造真实 Mission→Run→Workspace 验收；AgentOS 全量测试仍有四个既有失败族，见“Full regression”。因此不能把本报告标为 P0 COMPLETED。

## P0 defects

| P0 项 | 收敛结果 | 证据/限制 |
| --- | --- | --- |
| Java RuntimeEvent SSE gateway | 已实现 | Java GET 代理、无缓冲 SSE、Fake upstream 300ms 流式测试通过 |
| 原生生产模型真流 | 已实现 | `streamingCapability` 进入冻结 binding；生产 Gateway runtime 禁止静默 sync fallback |
| 正式 Workspace 消费 | 代码已接通 | MissionWorkspace、GraphEditor、RuntimeInspector、ProjectRunSidebar 共用一个 Store/一个 EventSource；缺真实登录态验收 |
| Retry attempt 隔离 | 已实现 | 每次重试生成新 attemptId；新 attempt 清空旧 output，迟到旧事件被忽略 |
| Cancel 传播 | 代码和单测已覆盖 | Run→Workflow task→model stream→provider iterator 的取消链已接通；真实 provider 端到端时间线未验收 |
| Broker 背压策略 | 已实现 | 可合并 delta/activity；关键生命周期事件不静默丢弃，无法保留时显式 overflow |
| `node.failed` | 已实现 | 安全 payload 含 `errorCode`、`retryable`、`attempt` |
| Broker/Store 生命周期 | 已实现 | terminal event 后 SSE 结束；Store acquire/release 后订阅与 Broker 队列清理 |
| Planner 集成 | 已收敛 | 复用既有 Broker/SSE/Store/RunProgressEditor；共享 deadline 失败已修复 |

## Files changed

### AgentOS / Python Runtime

- `agent/app/api/agentos_v2.py`
- `agent/app/execution/coordinator.py`
- `agent/app/execution/model_runtime.py`
- `agent/app/execution/wiring.py`
- `agentOS/service/agents/base.py`
- `agentOS/src/adapters/guarded_model.py`
- `agentOS/src/adapters/model/native.py`
- `agentOS/src/adapters/model_runtime.py`
- `agentOS/src/components/executor/node_runner.py`
- `agentOS/src/components/planner/complexity.py`
- `agentOS/src/runtime/app_setup.py`
- `agentOS/src/runtime/live_events.py`
- `agentOS/src/runtime/workflow_runtime.py`

### Java Gateway

- `backend/src/main/java/com/kinlin/ai/controller/AgentOsGatewayController.java`
- `backend/src/main/java/com/kinlin/ai/gateway/AiSseGatewayService.java`

### Frontend / proxy

- `frontend/nginx.conf`
- `frontend/src/workbench/runtime/runtimeEvents.ts`
- `frontend/src/views/MissionWorkspaceView.vue`
- `frontend/src/components/workspace/GraphEditor.vue`
- `frontend/src/components/workspace/RuntimeInspector.vue`
- `frontend/src/workbench/contributions/project/ProjectRunSidebarView.vue`

### Tests

- `agent/tests/test_agentos_v2_api.py`
- `agentOS/tests/test_runtime_live_events.py`
- `agentOS/tests/adapters/test_guarded_runtime.py`
- `backend/src/test/java/com/kinlin/ai/gateway/AiSseGatewayServiceTest.java`

## Final chain

```text
Mission
  → Java AgentOS Gateway
  → Python WorkflowRuntime
  → Planner / Node true stream
  → RuntimeEventBroker
  → Python SSE /ai/agentos/v2/runs/{runId}/events
  → Java SSE proxy /api/agentos/v2/runs/{runId}/events
  → frontend shared RunRuntimeStore
  → MissionWorkspace
     ├─ RunProgressEditor
     ├─ GraphEditor
     └─ ProjectRunSidebar / RuntimeInspector
```

Java gateway 增加了 GET SSE 入口，使用现有 `AiSseGatewayService` 的 WebClient 连接、认证头转发、超时和连接错误映射；响应保持 `text/event-stream`，上游 Flux 不收集、不等待完成。下游取消会取消上游订阅，但观察者 SSE 断开不会调用 Workflow cancel。`frontend/nginx.conf` 对 RuntimeEvent 路径单独关闭 proxy buffering/cache，启用 HTTP/1.1 长连接和 `X-Accel-Buffering: no`。

## Java SSE architecture

`AgentOsGatewayController` 暴露：

```text
GET /api/agentos/v2/runs/{runId}/events
  → GET /ai/agentos/v2/runs/{runId}/events
```

`AiSseGatewayService.openGet` 使用 `toEntityFlux(ServerSentEvent<String>)`，没有把事件物化为列表。测试 Fake upstream 每 300ms 发出 `model.output.delta`、`node.completed`，Java 测试在上游结束前读取到第一条事件，证明代理不是“等上游完成后再返回”。

## Native model binding

生产 binding 在 Run 启动时冻结并审计 `provider`、`model`、`version`、`streamingCapability`；默认配置也只作为显式生产 binding 来源，不在执行中重新选择 provider/model。`GatewayStructuredGenerationRuntime` 标记生产流必需，`NativeModelAdapter` 在没有 `astream` 时返回明确的 `MODEL_STREAM_UNSUPPORTED`，不会静默走同步生成。

节点运行上下文现在携带 `attemptId`。`node.started`、model stream event、`node.completed` 和 `node.failed` 使用同一节点 attempt 语义，避免用 commitId 冒充模型重试身份。

## Formal Inspector

`MissionWorkspaceView` 负责按 `runId` acquire/release 共享 Store；`GraphEditor` 与 `RuntimeInspector` 接收同一个 Store；正式 `ProjectRunSidebarView` 消费该 Store，显示 runId、节点显示名、phase、attempt、duration 和 live output。前端 RuntimeEventClient 对每个 Run 只创建一个 EventSource，并在 `run.completed`、`run.failed`、`run.cancelled` 后关闭。

本轮真实浏览器只验证了新容器的首页入口：页面标题为“首页 - 知弈 AgentOS”，主导航和进入入口可见。没有登录态，未声称正式 Workspace UI 已通过业务验收。

## Retry semantics

Guarded model 每次尝试创建独立 attemptId，重试格式为 `base:retry:<uuid>`；不会复用旧 kwargs 中的 attemptId。前端检测到新 attempt 时重置 phase/status/output/chunks，旧 attempt 的迟到 terminal/delta 事件不会拼接到新 attempt。对应测试验证了首尝试产生 chunk 后超时，重试产生全新的 attemptId 和独立输出。

## Cancellation

取消入口调用 `runtime.cancel(runId)` 并取消 Coordinator 管理的 Workflow task；Coordinator 在捕获 `CancelledError` 时重新读取持久化 Run 状态，已是 `CANCELLED` 的 Run 不会被误写成 `FAILED`。模型流和 provider iterator 保留异步取消/`aclose` 路径，Run terminal event 发布后 SSE 结束；SSE 观察者断开只清理订阅，不把观察者离开误判为用户取消。

已有取消测试覆盖 partial chunk 后 cancel、无后续 chunk 和 WorkflowRun `CANCELLED`。真实 provider 的网络连接关闭和正式 UI cancel 时间线仍需登录态验收。

## Broker policy

Broker 仅使用进程内实现，没有引入 Redis、Kafka 或 Event Sourcing：

- 可合并：`model.output.delta`、`model.activity`、`planner.model.activity`。
- 不可静默丢弃：`node.completed`、`node.failed`、`model.completed`、`planner.completed`、`planner.failed` 以及 Run terminal lifecycle event。
- 队列满时，关键事件优先移除最老的可合并事件；如果队列内全是关键事件，发布失败为显式 `RuntimeEventOverflow`，SSE 返回 `runtime.subscriber.overflow` 与 `RUNTIME_SSE_SLOW_SUBSCRIBER`，而不是吞掉生命周期事实。
- terminal 后删除 subscriber、sequence 和 Run Broker 状态；前端引用计数归零时关闭 EventSource。

## Planner integration

Planner 继续复用已有 RuntimeEventBroker、Python SSE、RunRuntimeStore 和 RunProgressEditor，没有新增 Planner 专用 SSE。Planner 模型调用的共享 deadline 在最终无重试超时时转换为可识别的 `MODEL_TIMEOUT`，避免测试和运行时因 deadline 过期而无限等待。

## HTTP E2E

已验证的 HTTP/组件证据：

1. Java Fake upstream 以 300ms 间隔产生事件，Java SSE gateway 在 upstream 完成前读到第一条事件。
2. Python FastAPI TestClient 访问 `/ai/agentos/v2/runs/{runId}/events`，收到 delta、node.completed、run.completed，并在 terminal event 后结束响应；publisher 完成后 Run 仍保持测试预设状态。
3. AgentOS focused streaming/cancel/retry/planner/native 测试：`26 passed`。

尚未完成一条同一进程/真实部署中的“Fake Provider→Python WorkflowRuntime→Python SSE→Java Gateway→浏览器”全链路 HTTP 测试，也未完成带真实 provider 的 Planner HTTP E2E。这是 P0 正式验收的剩余证据，不应由分段测试替代。

## Real Provider timeline

未执行正式登录态 Mission/Run/Provider 时间线验收。当前 `.env.windows` 已配置 provider/model 选择，容器 readiness 和源码 binding 已验证；但没有授权的登录凭据，无法安全地产生真实 Run，也无法证明真实 GLM provider 的首个 delta、attempt、node.completed、Run terminal event 在 Java SSE 和正式 Workspace 中依次出现。此前直接 provider 探针只证明 provider 可达，不等价于正式链路验收。

## Full regression

| 范围 | 结果 |
| --- | --- |
| AgentOS streaming focused | 26 passed |
| Agent full test suite | 162 passed，26 warnings |
| Frontend Vitest | 57 files，301 tests passed |
| Backend Maven | 全量 `mvn -q test` passed |
| Frontend production build | Docker 当前 HEAD build passed；保留既有大 chunk warning |
| Runtime containers | frontend/backend/ai-service 均为 2026-09-03 新构建镜像，容器 healthy |
| Frontend `/health` | HTTP 200 |
| Backend `/health/ready` | `postgres=true`、`redis=true` |
| AI `/health/ready` | `dataDirectory=true`、`packsRegistered=true`、`workflowStore=true` |

AgentOS 全量结果为 `413 passed, 4 failed, 54 warnings`。四个失败为：

- `tests/runtime/test_identity_projection_lifecycle.py::test_projection_replay_repairs_partial_blueprint_registration`：`run.prepared` 投影回放中的既有 `StopIteration`。
- `tests/runtime/test_resource_binding.py::test_long_run_refreshes_local_agent_heartbeat_before_later_step`：资源绑定等待超时。
- `tests/runtime/test_resource_binding.py::test_impossible_frozen_binding_fails_instead_of_polling_forever`：全量顺序下资源绑定等待超时；单测单独重跑曾通过，具有顺序敏感性。
- `tests/runtime/test_resource_binding.py::test_capacity_queue_has_a_bounded_failure_outcome`：资源绑定等待超时。

这些失败不属于本轮 RuntimeEvent/SSE/Store 改动，但全量回归未清零，故不把整体状态写成 COMPLETED。

## Remaining P1/P2

P0 验收剩余项：

1. 使用真实授权登录态创建 Mission/Run，记录真实 provider 首 delta、attempt、node lifecycle、Run terminal event，并在正式 Workspace 截图/浏览器断言。
2. 增加或运行同一条 Python SSE→Java SSE proxy 的组合 HTTP E2E，以及 Fake Provider/Planner 的正式入口测试。
3. 分离并处理 AgentOS 全量中的 identity projection 与 resource binding 四个失败，确保最终回归清零或形成明确基线豁免。

P1/P2 可后续处理：前端既有大 chunk warning、Vue icon warnings，以及资源绑定/身份投影的非 Streaming 专项稳定性。

## Final Verdict

**代码链路已完成 P0 收敛，正式验收状态为 `P0 PARTIAL / ACCEPTANCE BLOCKED`，不是 `P0 COMPLETED`。**

本轮已停止在 P0 收敛边界，没有进入 Phase 3，也没有引入第二套 RuntimeEvent、Broker、SSE 或 Content/Control Plane 改造。剩余工作仅是获得授权后的真实链路验收、组合 HTTP E2E 补证和全量回归失败族收敛。
