# PR-C2B-INT-2B-1 — HTTP/API 最小正式闭环

日期：2026-10-25。验收基线与开始时 HEAD 均为 `aebab1f76281837050fef54e698b1662a8419159`；开始时 `git status --short` 无输出。本报告依据当前生产源码及本轮测试，不以历史审计判断接口存在与否。

## 当前生产链路审计

以下路径省略 `/agentos/v2`。表中“原有”指本轮修改前的基线源码。

| 分类 | 原有 HTTP 入口 | 实际调用链 / 权威 | 结论 |
| --- | --- | --- | --- |
| 已接正式 C2 | `POST /missions` | 可信身份 → `prepare_execution_input` → `create_mission` → `MissionSemanticService.commit` → `prepare_run(defer_acg_planning=True)` → `coordinator.submit` → `execute_prepared_run` → `_materialize_deferred_acg_run` → `_materialize_acg_run` → `RuntimePlanningCommitAuthority.accept_initial` | C2 开启时已有正式初始接受流程；不能另建客户端上传 TaskPlan/Commit 的接受入口。接受只写 Commit/outbox，保留 deferred Run，不执行节点。 |
| 条件接正式 C2 | `POST /missions/{mission_id}/runs`、`POST /missions/{mission_id}/runs/{run_id}/revision/{operation_id}/apply`、Review 的 rerun 分支 | 已有幂等/关联校验后调用 `prepare_run`、Coordinator；新 ACG Run 在启用 Planning Commit Authority 时标记 `planningCommitRequired` | 复用同一初始接受链；revision/apply 创建 successor，不是原地 Graph Activation。 |
| 正式 Mission 语义，非 C2 图推进 | `POST /missions/{mission_id}/semantics`；`POST /missions/{mission_id}/runs/{run_id}/revision` | `MissionSemanticService.commit` / `decide_run_revision`，可信 semantic principal，operationId、revision、receipt | 不能将 Mission revision receipt 当成 Planning Commit 或 Activation。 |
| Legacy / 既有 Planner 控制 | `POST /runs/{run_id}/copilot/answers`、`/copilot/actions/preview`、`/copilot/actions`、`/reviews`、`/steps/{step_id}/retry`、`/cancel` | `RuntimePlanningInteraction`、`RuntimeTaskOperations`、Review/Recovery/取消门面；可能进入 Coordinator 或执行入口，但不调用 materialization/activation/handoff/permit | 不是 Initial C2 图控制入口；不能借 approval 恢复尚无 Permit 的激活图。执行门面保留持久授权防线。 |
| Legacy 兼容分支 | 上述创建/执行入口在 C2 关闭时 | 无 Planning Commit Authority，既有 L1/L2/L3 规划、编译及调度 | 保留原行为；不自动给 Legacy Run 补 C2 权威事实。 |
| 只读投影 | `GET /runs/{run_id}`、`/graph`、`/checkpoints`、`/trace`、`/events`、`/provenance`、Mission workspace/history、Identity execution-tree/attempts/step-executions | Runtime / Identity / checkpoint / provenance 查询 | 原 Run 响应的 `_state` allowlist 不含 `graphActivation`；Identity 图可能在 Permit 身份投影前尚未出现。查询成功不等于图已获执行授权。 |
| 资源面辅助 | resources/nodes 注册、credential rotate、heartbeat/observation、启停及 probe | ResourcePlane、签名验证、资源版本，部分通知 Coordinator | 不签发 Graph Execution Permit，不是图状态推进入口；注册/轮换按既有合同一次返回资源凭据，不属于本次控制响应。 |
| 真正缺失 | 无 HTTP 调用 `materialize_initial_commit`、`prepare_graph_activation`、`commit_graph_activation` | 这些 Runtime 门面及 Authority 已存在 | 只新增两个 HTTP 适配入口；不新增 Authority、Store、Schema。 |
| 本轮范围外 | Handoff / Permit 的 HTTP 控制 | Runtime 已有 `prepare_graph_handoff` / `issue_execution_permit`，基线无 HTTP 调用 | 本轮刻意不接入，也不自动调用。 |

`apps/agent/app/execution/wiring.py` 已按 operator 预升级的 SQLite 装配 Planning Commit → Materialization → Activation → Handoff → Permit，并校验 C2 必须依赖 semantic convergence。没有修改装配、Coordinator、Authority 或核心合同。

Runtime 的额外公开能力 `apply_semantic_patch` / `accept_graph_revision` 已存在；前者在 C2 下调用 `accept_patch_locked` 而不直接替换图。本次 Initial HTTP 链无需新增它们的路由。现有 Planner revision 在 C2 下先经 `_gate_planning_commit_decision`，不能把 Legacy semantic replacement 当成 C2 激活。

## 本轮改动

1. `apps/agent/app/api/agentos_c2.py`：两个 Initial 控制适配入口、可信身份/归属校验、预期版本校验、已有 Authority 回执映射、只读正式状态投影。
2. `apps/agent/app/api/agentos_v2.py`：挂载上述路由；已有 Run GET 添加 `formalControl`；C2 模式拒绝在业务 input 中上传 principal、Permit、GraphVersion、执行收据等控制字段。
3. `apps/agent/tests/test_agentos_c2_http.py`：FastAPI TestClient + 真实生产 Runtime 装配 + 临时 SQLite；仅业务 Agent/模板及离线 Planner 为确定性夹具，认证中间件和所有 Authority 均未替换。
4. 本审计报告。

新增端点：

- `POST /missions/{mission_id}/runs/{run_id}/graph/materializations`
- `POST /missions/{mission_id}/runs/{run_id}/graph/activation`

两个入口只操作正式接受的 Initial Commit；请求不允许额外字段。`expectedGraphId` / `expectedGraphVersion` 只是对持久 materialization 的比较条件，不能构造 GraphVersion。Materialization 及 Activation 都由原 Authority 生成并验证。

operationId 经可信 tenant/actor、action、Mission、Run 命名空间散列映射为既有 Authority 的 idempotencyKey；不新增回执表。相同操作重放返回同一个持久 ID 和 `IDEMPOTENT_REPLAY`；其他 key 竞争同一来源仍由原 Authority 返回冲突。预期版本始终与不可变来源事实比较，因此激活后的原请求可以重放，篡改预期版本仍被拒绝。

Activation HTTP 调用依次执行既有 prepare / commit 两阶段。阶段间失败允许保留 `ACTIVATION_PREPARED`；同 operationId 重试收敛。接口不假称两阶段是单个事务。最终 Head 与 Run 原子切换仍由 `GraphActivationAuthority.commit` 唯一负责。

## HTTP 示例

下面为字段形状示例，ID 使用占位符。浏览器用户先经过可信上游身份认证；Python 中间件还要求内部服务凭据。`X-Authenticated-*` 只有在有效内部服务 token 同时存在时才被接受，不能将下面的上游协议视为公开客户端可任意声明的身份。

```http
POST /agentos/v2/missions
X-Internal-Service-Token: <trusted-service-token>
X-Authenticated-User-Id: owner
X-Authenticated-User-Subject: upstream-subject
X-Authenticated-User-Role: user
X-Authenticated-Tenant-Id: tenant
Content-Type: application/json

{"title":"Contract review","workflowId":"offline_contract_review","clientRequestId":"create-1","input":{"contractText":"<business material>","deterministicIntent":true},"semantics":{"objective":"Review the contract and produce a traceable report","constraints":[],"sourceRefs":["input:contractText"]}}
```

返回 `202`，复用已有 `MissionResponse`，包含 `missionId`、`runId`、`status`、`runtimeRevision` 等生命周期字段。`offline_contract_review` 为测试中注册的业务工作流，示例不承诺生产已安装同名工作流。

```http
GET /agentos/v2/runs/<run-id>
```

规划接受后，已有响应增加：

```json
{"formalControl":{"status":"PLANNING_ACCEPTED","executionAuthorized":false,"commitId":"<commit-id>","commitmentRevision":1,"materializationId":null,"activationId":null,"graphId":null,"graphVersion":null}}
```

```http
POST /agentos/v2/missions/<mission-id>/runs/<run-id>/graph/materializations
Content-Type: application/json

{"operationId":"materialize-1","commitId":"<commit-id>","expectedCommitmentRevision":1}
```

```json
{"operationId":"materialize-1","status":"MATERIALIZED_INACTIVE","materializationId":"<materialization-id>","graphId":"<graph-id>","graphVersion":1}
```

```http
POST /agentos/v2/missions/<mission-id>/runs/<run-id>/graph/activation
Content-Type: application/json

{"operationId":"activate-1","materializationId":"<materialization-id>","expectedGraphId":"<graph-id>","expectedGraphVersion":1}
```

```json
{"operationId":"activate-1","status":"ACTIVATED_PAUSED","activationId":"<activation-id>","activeGraphVersion":1}
```

再次 GET Run 的 `formalControl.status` 为 `ACTIVATED_PAUSED`、`executionAuthorized` 为 `false`，包含持久 Commit/Materialization/Activation/Graph 引用。原有 `status` 仍按已冻结的 Workflow lifecycle 枚举返回（Initial 链通常为 `planning`）；没有发明或改写核心 `paused` 枚举。不得用原 lifecycle 单独判断执行许可。

HTTP 错误：身份失败 `401/403`（中间件）；权限不足 `403`；错误关联/预期版本/Authority 冲突 `409`；额外控制字段 `422`；证据存储或中断 `503`。Authority 拒绝仅投影稳定 code、status、operationId，不返回内部 reason、来源快照、签名、编译包或审计体。

## 执行授权证据

- HTTP 初始创建经后台正式接受；新增两个图控制入口均无 `coordinator.submit`、Handoff 或 Permit 调用。
- Authority 激活投影为 `ACTIVATED_PAUSED`，`executionPermit` 为空；正式 GET 在 SQLite 读取事务中调用现有 `validate_activation_run` 验证 Head/Activation/Materialization/Run。
- HTTP 测试检查 Agent 调用为空、节点执行提交为空、Handoff/Permit 表为空。显式再调用 `execute_prepared_run` 时，既有 `ExecutionPermitAuthority.assert_dispatchable` 抛出 `ExecutionPermitError`，仍零节点执行。
- 重构服务并执行 Coordinator startup 后仍读取同一正式状态；原 key 的 Activation 仍可重放。
- 再以 C2/semantic 均关闭、Legacy intent 开启的装配重构同一测试数据库：正式状态仍可查询，写入口返回 409，`execute_prepared_run` 不推进也不新增事实，零 Agent 调用。
- 拒绝及重放请求比较 Run、Planning Commit/outbox、Materialization、Activation、Head、Handoff、Permit 的完整表行，确认没有额外事实。
- 控制响应使用 allowlist，不暴露内部 token、principal、sourceProvenance、idempotencyKey、packageChecksum、签名或业务输入。

## 验证结果与边界

以下为本轮实际运行结果，各组不代表全量测试或部署验收：

| 定向范围 | 命令（均从仓库根目录运行） | 结果 |
| --- | --- | --- |
| 最终 HTTP 测试 | `python -m pytest apps/agent/tests/test_agentos_c2_http.py -q --disable-warnings --maxfail=1` | **11 passed, 2 warnings in 21.00s** |
| HTTP + 已有控制合同 / Coordinator / 内部认证 | `python -m pytest apps/agent/tests/test_agentos_c2_http.py apps/agent/tests/test_agentos_control_contracts.py apps/agent/tests/test_execution_coordinator.py apps/agent/tests/test_internal_service_auth.py -q --disable-warnings --maxfail=1` | **27 passed, 3 warnings in 35.89s**；此后补充关闭 Authority 的查询兼容逻辑及更强的 HTTP 断言，最终 HTTP 11 项再次通过。 |
| 既有 v2 API / 生产装配回归 | `python -m pytest apps/agent/tests/test_agentos_v2_api.py apps/agent/tests/test_execution_runtime_application_wiring.py -q --disable-warnings --maxfail=1` | **60 passed, 2 warnings in 24.78s** |
| C2 Runtime / Authority 回归 | `python -m pytest apps/agentOS/tests/components/planner/test_production_authority_assembly.py apps/agentOS/tests/components/planner/test_initial_graph_materialization.py apps/agentOS/tests/components/planner/test_graph_activation.py apps/agentOS/tests/components/planner/test_planning_commit_runtime.py -m 'not slow_multiprocess and not slow_fault_injection' -q --disable-warnings --maxfail=1` | **88 passed, 1 warning in 131.66s** |

HTTP 11 项包括：真实链路/同 key 重放及竞争 key 冲突/重构读取、无效凭据和越权防线、错误 Mission/Run/Graph 关联、预期版本拒绝、业务输入及命令体权威字段拒绝、prepare 后中断再收敛、Mission revision 变化后拒绝旧来源、六种有效开关组合及 C2 无 semantic convergence 的装配拒绝。已有内部认证测试另覆盖缺失/错误/空/重复 token 和无可信身份。测试夹具曾因构造线程与 TestClient 服务线程不一致触发 SQLite 线程限制，已在服务 lifespan 内构造和关闭真实 Runtime 后通过；未为此修改生产 Store。

`git diff --check` 通过。开始及结束 HEAD 相同。未运行全量 pytest；未运行或清空 freeze gate 历史耗时缓存。本轮未发现阻止此 Initial 最小闭环的结构性 P0/P1；不把这些定向测试结果声称为完整运行系统验收。

剩余范围：不提供 Handoff/Permit HTTP 入口，不执行节点，不扩展 Graph Revision 的 HTTP 控制，不实现前端。正式状态不以 Identity 投影是否已出现为条件；现有 `/graph` 的 Identity 投影可用性合同保持原样。服务在接受后、激活前崩溃的 orphan 处理仍沿用原合同，本轮重构恢复验证覆盖已持久激活的 PAUSED 边界。

未提交、未推送、未部署；未修改生产开关、前端、compose 或真实业务数据库。完成后停在 INT-2B-1，等待独立验收。

## INT-2B-1-FREEZE 归档

收到后续连续执行授权及独立审查 `ACCEPT WITH LIMITATIONS` 后，仅校验并归档本阶段，三个源码文件未重新设计。

新鲜回归：`python -m pytest apps/agent/tests/test_agentos_c2_http.py apps/agent/tests/test_agentos_v2_api.py apps/agent/tests/test_internal_service_auth.py apps/agent/tests/test_agentos_control_contracts.py -q --disable-warnings --maxfail=1` → **75 passed, 3 warnings in 34.80s，退出码 0**（包含原 HTTP 11 项）。`git diff --check` 通过。

本次回归前后三文件 SHA256 校验一致：`agentos_c2.py` 为 `e7b77adb83a92c7b6f255d9244ce2b2bfa08c8192b5d16b33a62f0118a9cbdd4`；`agentos_v2.py` 为 `50bae5369cc91bf29fbf62e005ba850bd095087523d3e2bd4b4bc058973a15b6`；`test_agentos_c2_http.py` 为 `8e0c1e6ad656cc670b36274ebcf95d2865db0a888467b2df74c8da6e05c413ed`。固化 Commit 由后续 `PR-C2B-INT-2B-2.md` 记录，避免自引用 Commit SHA。

工作区另有 `docs/audits/审计汇编-中文.md` 的用户删除，不纳入此提交。前述“未提交”是 Initial 阶段交付时的历史状态，本节记录后续获授权的固化。
