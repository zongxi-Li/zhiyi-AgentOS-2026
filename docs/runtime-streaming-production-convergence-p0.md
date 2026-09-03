# 知弈 AgentOS — Runtime Streaming Production Convergence P0

- 日期：2026-09-03
- 分支：`master`
- 实施前 HEAD：`840f630d4ab21d8726b931613f7949a8ade77122`
- 当前代码提交：`88719cb`、`633346e`、`1550bcc`
- 唯一可信审计基线：`docs/runtime-streaming-final-chain-audit-2026-09-03.md`
- 审计基线 Verdict：`BROKEN`
- 范围：仅收敛 Runtime Streaming P0；不进入 Phase 3，不新增 Content Plane、Control Plane 或第二套 RuntimeEvent/Broker/SSE。

## 1. Baseline

实施前已记录：

- 分支为 `master`。
- HEAD 为 `840f630d4ab21d8726b931613f7949a8ade77122`。
- 工作区已有用户文件 `docs/runtime-streaming-final-chain-audit-2026-09-03.md`，本轮未修改、未提交。
- 审计确认正式入口是 `/agentos/acg → AcgEntryView → MissionWorkspaceView`；`AcgVisualizationView`、`AcgRunInspector` 和 debug page 不作为产品完成证据。
- 主要断点是 Java RuntimeEvent SSE mapping 缺失、Native 生产链存在同步 fallback 风险、正式 Workbench 未共享 Runtime Store、retry attempt 隔离不足、取消未证明到 provider iterator、Broker critical event 丢失风险，以及真实链路证据不足。

本报告不引用历史“Phase 1-2 已完成”或“Planner Streaming 已完成”报告作为事实基础。

## 2. Audit defects addressed

| P0 项目 | 当前代码/测试结论 | 正式验收结论 |
| --- | --- | --- |
| Java RuntimeEvent SSE gateway | 已增加 GET 代理、`text/event-stream`、上游取消传播和 300ms 早到测试 | 已验证 |
| Python SSE/Broker | 已复用既有 Broker 与 FastAPI SSE，保持单一事件流 | 已验证 |
| Native production true streaming | 正式 binding 冻结 provider/model/streaming capability；不支持时显式失败，不静默同步降级 | 已验证 |
| Planner streaming | 复用 RegisteredPlannerLLM、既有 Broker/SSE/Store/RunProgressEditor | 已验证 |
| Formal Workbench Store | MissionWorkspace、Graph、RunProgressEditor、ProjectRunSidebar/Inspector 接入共享 Store | 代码与 Fake SSE 已验证 |
| Retry new attempt | Guarded runtime 生成新 attemptId，前端按 `(runId,nodeId,attemptId)` 隔离 | 已验证 |
| Cancel to provider | provider iterator 的 `aclose()` 有专门测试，显式取消与 SSE observer disconnect 分离 | 代码/单测已验证，真实 Provider 时间线未验证 |
| Broker critical events | delta/activity 可合并；critical 事件不静默淘汰，满载时显式 overflow | 已验证 |
| node.failed | 正式 Node failure path 发布安全摘要 payload | 已验证 |
| Lifecycle cleanup | terminal 后清理 Broker transient state；Store acquire/release 关闭 EventSource | 已验证 |
| Real production acceptance | 缺少可用登录凭据和真实 Provider Workbench 时间线 | 阻断 |

## 3. Files changed

本轮涉及的功能边界如下；其中前几轮已提交的 Runtime 实现文件保持不变，本轮新增/修改的文件已按功能边界分布提交。

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
- `backend/src/test/java/com/kinlin/ai/gateway/AiSseGatewayServiceTest.java`

### Frontend / Workbench

- `frontend/nginx.conf`
- `frontend/src/workbench/runtime/runtimeEvents.ts`
- `frontend/src/views/MissionWorkspaceView.vue`
- `frontend/src/views/MissionWorkspaceView.spec.ts`
- `frontend/src/components/workspace/GraphEditor.vue`
- `frontend/src/components/workspace/RuntimeInspector.vue`
- `frontend/src/workbench/contributions/project/ProjectRunSidebarView.vue`
- `frontend/src/components/workspace/RunProgressEditor.spec.ts`

### E2E / lifecycle tests

- `agent/tests/test_runtime_streaming_production_e2e.py`
- `agentOS/tests/adapters/test_model_runtime_streaming.py`
- `scripts/runtime_streaming_combined_acceptance.py`
- `agent/tests/test_agentos_v2_api.py`
- `agentOS/tests/test_runtime_live_events.py`
- `agentOS/tests/adapters/test_guarded_runtime.py`

## 4. Production route/component tree

正式产品入口固定为：

```text
/agentos/acg
  → AcgEntryView
  → MissionWorkspaceView
  → RuntimeInspector / SecondarySidebar
  → ProjectRunSidebarView
```

正式运行时数据拓扑为：

```text
runId
  → Shared RunRuntimeStore
     ├─ GraphEditor
     ├─ RunProgressEditor
     └─ ProjectRunSidebarView / RuntimeInspector
```

`AcgVisualizationView`、`AcgRunInspector` 和 debug page 仍是非正式路径，不用于 P0 完成判定。

## 5. Final Node production chain

```text
Mission
  → Java AgentOS Gateway
  → Python WorkflowRuntime
  → model binding freeze
  → NativeGeneralAgent
  → RegisteredModelRuntime.stream_generate_json()
  → NodeRunner
  → RuntimeEventBroker
  → FastAPI /ai/agentos/v2/runs/{runId}/events
  → Java /api/agentos/v2/runs/{runId}/events
  → shared RunRuntimeStore
  → Graph / Inspector / Output
```

Node 在完成前发布 `node.started`、`model.started`、`model.first_token` 和 `model.output.delta`；完成后才发布 `model.completed`、`node.completed`。

## 6. Final Planner production chain

```text
Mission Run
  → PlanningEngine
  → RegisteredPlannerLLM
  → planner RuntimeEvent
  → RuntimeEventBroker
  → FastAPI run events SSE
  → Java RuntimeEvent SSE gateway
  → shared RunRuntimeStore
  → RunProgressEditor
  → profile / plan / graph projection
  → Node execution
```

Planner 不新增 `/planner-events`、第二个 EventSource、第二个 Broker 或 fake planner node。Planner intent profile、repair、outline、detail、relations 继续共享一个 planning total deadline。

## 7. Java SSE proxy design

Java 新增的正式映射为：

```text
GET /api/agentos/v2/runs/{runId}/events
  → GET /ai/agentos/v2/runs/{runId}/events
```

`AiSseGatewayService.openGet` 使用 WebClient 的 `toEntityFlux(ServerSentEvent<String>)` 逐事件转发，不收集完整响应、不等待上游关闭；响应保持 `text/event-stream`，并设置禁用缓存/缓冲的响应语义。客户端断开会取消 Java 到 Python 的上游订阅，但不会调用 Workflow cancel。

Java 集成测试使用 Fake upstream 按 A、300ms、B、300ms、C 的节奏发送，客户端在上游结束前已收到 A/B，证明代理没有缓冲到最后一次性返回。

## 8. Native streaming binding strategy

Run 启动时冻结并审计 `runId`、`nodeId`、`provider`、`model`、`version`、`streamingCapability` 与 binding source。NativeGeneralAgent 的正式执行只接受 streaming-capable RegisteredModelRuntime；缺失 `astream` 时产生显式 `MODEL_STREAM_UNSUPPORTED`，不静默进入同步黑盒。

兼容调用方仍可使用 legacy `generate_json()`，但正式 Native ACG Node 不通过该接口完成生产执行。安全审计数据不记录 prompt、secret、raw provider response 或 hidden reasoning。

## 9. Formal Inspector path

唯一正式 Inspector Streaming 路径是：

```text
MissionWorkspaceView
  → RuntimeInspector
  → SecondarySidebar
  → ProjectRunSidebarView
  → parent-provided RunRuntimeStore
  → latest node attempt outputBuffer
```

Graph 与 Inspector 由 MissionWorkspaceView 共享同一个 Store 和同一个 EventSource。`RuntimeInspector` 的独立挂载 fallback 现在也使用 acquire/release，并在 run 切换、父 Store 接管和 unmount 时释放，避免形成第二套长期连接。Output tab 显示 Node display name、phase、attempt、duration 和 live outputBuffer；sequence、chunkCount、provider request id 不作为默认产品信息。

## 10. Attempt/retry semantics

每次 Guarded runtime retry 都生成新的 attemptId，前端以 `(runId,nodeId,attemptId)` 作为状态边界。新 attempt 到达时清空当前显示的 phase/status/output，旧 attempt 的迟到 delta 或 terminal event 不会拼接进新 attempt。

目标时间线已由现有 retry 测试覆盖：

```text
Attempt 1: model.started → OLD → MODEL_IDLE_TIMEOUT
Attempt 2: new attemptId → model.started → NEW → success
```

最终 Inspector 只显示 latest/current attempt，旧 attempt 保留在 Trace/Attempt history 中。

## 11. Cancellation propagation

显式 Run cancel 的语义为：

```text
Cancel API
  → Workflow execution task
  → Node/model stream task
  → provider async iterator
  → aclose()
  → provider connection release
  → WorkflowRun = CANCELLED
```

新增 adapter 测试在消费方取消后断言 provider iterator 的 `finally`/关闭事件已发生。现有 cancellation 测试覆盖 partial chunk 后 cancel、后续 delta 停止和 Run `CANCELLED`。SSE observer 断开只释放订阅，不触发 Workflow cancel。

真实 Provider 的网络连接关闭与正式 UI Cancel 时间线尚未在当前环境完成，因此该部分不能标记为真实环境完成。

## 12. Broker overflow policy

Broker 的事件分类为：

- 可合并：`model.output.delta`、`model.activity`、`planner.model.activity`。
- critical：`model.completed`、`node.completed`、`node.failed`、`planner.completed`、`planner.failed` 以及 Run terminal lifecycle event。

队列满载接收可合并事件时允许合并/丢弃 delta；接收 critical 事件时优先移除最老的可合并事件再入队。如果队列只剩 critical，Broker 抛出显式 `RuntimeEventOverflow`，SSE 返回 `runtime.subscriber.overflow` / `RUNTIME_SSE_SLOW_SUBSCRIBER`，不静默覆盖或丢弃 critical event。本轮未引入 Kafka、Redis Stream 或 Event Sourcing。

## 13. Lifecycle cleanup

Run terminal 后清理 subscriber queues、run sequence 和 Broker transient state；SSE 在 terminal event 后结束。前端 RuntimeEventClient 使用按 runId 的共享连接，Store 采用 acquire/release 引用计数：Graph 与 Inspector 共享连接，run switch 和 unmount 释放旧连接，引用归零后关闭 EventSource，不永久保留已完成 Run 的 Store。

本轮正式 Workbench 测试发现并修复了 Vue `ref` 包装 Store 导致 release identity 不一致的问题，改用 `shallowRef`，从而使 unmount 后 EventSource 确实关闭。

## 14. Native HTTP E2E

新增 `agent/tests/test_runtime_streaming_production_e2e.py`，通过真实本地网络 HTTP 启动 Fake Streaming Provider 和 uvicorn FastAPI，链路覆盖：

```text
Fake Provider
  → RegisteredModelRuntime
  → NativeGeneralAgent
  → NodeRunner
  → RuntimeEventBroker
  → FastAPI SSE
  → HTTP client
```

测试断言 HTTP client 在 `node.completed` 前收到 `model.output.delta`，Run terminal event 正确到达，Provider 请求使用 stream，事件中不包含 prompt。该测试已通过。

同一 Java Gateway 的 A/B/C 早到集成测试也已通过，但当前尚未把 Python SSE 与 Java Gateway 放进同一条跨进程测试，因此不能把“Native HTTP E2E”写成完整 Java→Python→Browser 证据。

## 15. Planner HTTP E2E

同一 E2E 文件新增 Planner 网络测试，真实调用 Fake Planner Provider、RegisteredPlannerLLM、PlanningEngine、RuntimeEventBroker、FastAPI SSE 和 HTTP client。测试在 planning complete 前收到 `planner.model.started`、`planner.model.first_token`、`planner.model.completed` 与 `planner.completed`，并断言事件不泄露 raw JSON、prompt 或 reasoning content。

该测试已通过；其 Java Gateway 代理部分由第 7 节的 Java streaming integration test 覆盖，尚缺一条跨 Python SSE 与 Java Gateway 的同进程/跨进程组合测试。

## 16. Formal Workbench E2E

`MissionWorkspaceView.spec.ts` 的正式 Workbench 测试使用 Fake EventSource，进入正式 MissionWorkspace 路径而非 `AcgVisualizationView`，发送：

```text
node.started
model.started
model.first_token
delta "A"
delay
delta "B"
```

测试已验证 Graph/正式 Inspector 状态为 `STREAMING`，Output 先显示 `A`、随后显示 `AB`，且 persistent status 仍不是 `COMPLETED`；unmount 后共享 EventSource 被关闭。

`RunProgressEditor.spec.ts` 已验证 Planner live facts 在 Trace projection 追上前显示 Planning active、model active、TTFT/Idle、Call、Profile metrics，并验证不渲染 prompt、reasoning 或 raw JSON markers。

## 17. Real Provider timeline

当前已重建并启动当前工作区源码对应的 AI、Backend、Frontend 镜像；三个容器均 healthy，前端 `/health` 返回 200，Backend readiness 的 postgres/redis 均为 true，AI readiness 的 dataDirectory/packsRegistered/workflowStore 均为 true。正式前端首页和登录页已通过真实浏览器打开，Runtime Events 未授权请求返回 401，并保留 `X-Accel-Buffering: no`。

但当前环境没有可用的正式登录凭据，无法安全创建 Mission/Run，也没有可用于正式 Workbench 的真实 Provider 认证结果。因此以下时间线尚未取得：

```text
run_created
planner.started
planner.first_token
profile_resolved
plan_parsed
graph_compiled
first_node.started
first_node.first_token
first_sse_delta
first_visible_output
model.completed
node.completed
```

不能声称真实 Provider 已验收，也不能声称已经测得 `first_visible_output < node.completed`。

## 18. Regression

当前 HEAD/工作区验证结果：

| 范围 | 当前结果 | 归因 |
| --- | --- | --- |
| AgentOS full | `417 passed, 1 failed, 54 warnings` | 失败为 `test_projection_replay_repairs_partial_blueprint_registration`，隔离复现；`run.prepared` 未进入 pending projection queue，属于 `PRE_EXISTING_FAILURE`，不触及 Streaming/SSE/Store 改动 |
| Agent full | `164 passed, 28 warnings` | 通过 |
| Frontend Vitest | `57 files, 302 tests passed` | 通过 |
| Backend Maven full | `mvn -q test` 退出码 0 | 通过 |
| Java SSE targeted | `AiSseGatewayServiceTest` 4/4 | 通过 |
| Streaming focused | AgentOS streaming/cancel/retry/planner/native focused `15 passed` | 通过 |
| Native/Planner HTTP E2E | `2 passed` | 通过，仍缺 Java Gateway 组合段 |
| Frontend production build | `npm run build:web` 通过 | 通过，保留既有大 chunk warning |
| Runtime containers | AI/Backend/Frontend healthy | 通过 |
| Browser public entry | 首页、登录页真实浏览器快照通过 | 通过；无登录凭据，未进入正式 Workbench |

### Combined Java → Python E2E

由 `scripts/runtime_streaming_combined_acceptance.py` 运行真实跨进程链路：

```text
Fake Provider
  → RegisteredModelRuntime
  → NativeGeneralAgent / PlanningEngine
  → RuntimeEventBroker
  → Python FastAPI SSE
  → Java Spring Boot SSE Gateway
  → Java-facing HTTP client
```

| 项目 | 结果 | 证据 |
| --- | --- | --- |
| Native combined E2E | PASS | 事件顺序包含 `node.started → model.started → model.first_token → model.output.delta → model.completed → node.completed → run.completed` |
| Planner combined E2E | PASS | 收到 `planner.started`、`planner.model.started`、`planner.model.first_token`、`planner.model.activity`，并在 `planner.completed` 前到达 |
| Early SSE delivery | PASS | Native `firstDeltaBeforeNodeCompleted=true`；Java client 在 Python upstream 完成前收到事件 |
| Disconnect isolation | PASS | Java client 收到首个事件后断开；Python subscription closed，Workflow 仍为 `completed` |

该脚本没有直接访问 `broker._queues`，没有 mock Java service method，也没有跳过 Java HTTP。Java Gateway 使用当前 Backend jar 的真实 Spring Boot HTTP endpoint；Java dev profile 仅用于自包含验收会话，不代表正式产品认证验收。

### Real Product Acceptance

| 验收项 | 结果 | 说明 |
| --- | --- | --- |
| Authentication | BLOCKED | 没有可用于正式产品 Workbench 的认证会话；未绕过鉴权 |
| Real Provider | BLOCKED | 未取得真实 Provider 正式调用凭据 |
| Planning live | NO | 未进入正式登录后的真实 Mission/Run |
| Graph materialized | NO | 未进入正式登录后的真实 Mission/Run |
| Node STREAMING | NO | 未进入正式登录后的真实 Mission/Run |
| Inspector output before completion | NO | 未进入正式登录后的真实 Mission/Run |
| Output continued growing | NO | 未进入正式登录后的真实 Mission/Run |
| Refresh did not cancel Run | NO | 未执行正式 Workbench 刷新验收 |

因此正式产品验收状态为 `REAL_PRODUCT_ACCEPTANCE_BLOCKED_BY_AUTH`，不能把自包含 dev profile 组合测试等同于真实 Provider Workbench 验收。

### Baseline Regression Waiver

| test | baseline `840f630` | current `8ac6c16` | classification |
| --- | --- | --- | --- |
| `tests/runtime/test_identity_projection_lifecycle.py::test_projection_replay_repairs_partial_blueprint_registration` | FAIL；`StopIteration`，`run.prepared` 未进入 pending projection queue | FAIL；同一 `StopIteration` | `ACCEPTED_BASELINE_FAILURE` |

该测试在本轮前后均以同一栈失败，且不触及 RuntimeEvent、SSE、Broker、Native binding 或 Frontend Store。结论：`Streaming-introduced failures = 0`。本轮不修复该明确的 PRE_EXISTING_FAILURE。

## 19. Remaining P1/P2

剩余 P0 验收阻断：

1. 提供可用的正式登录/授权流程，创建真实 Mission/Run，记录 Planner、Node、SSE、Inspector 的完整时间线。
2. 在真实 Provider Workbench 中完成 Ctrl+Shift+R 刷新验收，证明 Workflow 继续运行、SSE 重新建立且后续事件继续到达。

跨进程 Java→Python 组合 E2E 已完成；identity projection replay 的全量失败已建立基线豁免，不再作为 Streaming 封板阻断。

P1/P2：前端既有大 chunk warning、少量 Vue unresolved icon warning、以及非 Streaming 的 resource binding/identity projection 稳定性，不在本轮 P0 Streaming 收敛范围内。

## 20. Final Verdict

**Runtime Streaming Production Convergence P0：`PARTIAL / REAL PRODUCT ACCEPTANCE BLOCKED BY AUTH`。**

本轮已完成代码层和自动化层的主要 P0 收敛：Java/Python SSE、Broker 分类、Native/Planner 真流绑定、正式 Workbench shared Store、retry attempt 隔离、cancel iterator close、node.failed 和生命周期 cleanup 均有实现与测试证据；当前 HEAD 的镜像也已正确重建并启动。

但是完成定义要求的真实 Provider 正式 Workbench 时间线和刷新验收仍因认证会话不可用而未完成。组合 Java→Python→HTTP E2E 已通过，唯一全量失败已被证明是 `ACCEPTED_BASELINE_FAILURE`，Streaming-introduced regression 为 0；但这不能替代真实产品验收。根据本轮要求，不能写 `Runtime Streaming Production Convergence P0 COMPLETED`。本轮在 P0 边界停止，不进入 Phase 3，不继续新增 Streaming 功能。
