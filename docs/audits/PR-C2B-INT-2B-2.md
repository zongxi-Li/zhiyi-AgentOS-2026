# PR-C2B-INT-2B-2 — Handoff / Execution Permit HTTP 集成

日期：2026-10-25。最终工程状态：**SELF-TESTED**，等待独立复验；不宣告独立 ACCEPT。推送因保留用户并行文档删除而阻断。

## INT-2B-1 固化与入场

任务 A 固化 Commit：`b0ea6c88c80754588a98679f6fc813646d3b4b4a`，标题 `feat(agentos-c2): 打通初始规划接受与图激活HTTP闭环`。

固化前 HEAD：`aebab1f76281837050fef54e698b1662a8419159`。开始时暂存区为空，未跟踪文件已完整核对；除已验收四文件，另有用户删除 `docs/audits/审计汇编-中文.md`。该删除完整保留，未暂存、未提交，也不恢复。本次固化只归档报告及提交已验收实现，三个源码文件与验收版本的 SHA256 前后一致。

固化新鲜回归：HTTP、既有 API、内部认证和控制合同共 **75 passed, 3 warnings in 34.80s，退出码 0**。实际命令：

```powershell
python -m pytest apps/agent/tests/test_agentos_c2_http.py apps/agent/tests/test_agentos_v2_api.py apps/agent/tests/test_internal_service_auth.py apps/agent/tests/test_agentos_control_contracts.py -q --disable-warnings --maxfail=1
```

## 真实架构审计与修改范围

审计以当前 `agentos_c2.py`、`agentos_v2.py`、Coordinator、wiring、`graph_handoff.py`、`execution_permit.py`、`initial_execution.py`、`graph_activation_store.py` 和现有相关测试为依据。

| 边界 | 实际权威 / 当前合同 | 本轮处理 |
| --- | --- | --- |
| 可信身份 | `InternalServiceAuthMiddleware` + `current_semantic_principal`；服务 token 验证后才信任上游身份；semantic service 检查当前 owner/tenant/write 权限 | 复用；命令体不能指定 principal |
| Handoff | `runtime.prepare_graph_handoff` → `GraphHandoffAuthority.prepare`；Workflow STAGING intent → 独立 Checkpoint DB stage → Workflow STATE_PREPARED confirmation | 新增 HTTP 适配；不构造 checkpoint，不修改 Authority |
| Permit | `runtime.issue_execution_permit` → `ExecutionPermitAuthority.issue`；PREPARING → checkpoint promotion → Identity promotion → Workflow ISSUED + Run 原子投影 | 新增 HTTP 适配；保留原 key 的跨库对账 |
| 派发许可 | `ExecutionPermitAuthority.assert_dispatchable` 验证持久许可、Head、当前 Mission revision、principal、Initial 来源、Identity 和 checkpoint；正式执行还调用 `assert_settled_operations` | 只读投影复用以上门禁；不复制 Permit 校验算法 |
| Coordinator | `submit()` 只接受未开始的 pending 或明确 retrying；Initial 已许可 Run 通常仍为 planning | 不放宽状态限制；不新增平行 Scheduler，不在 Handoff/Permit 后 submit |
| 实际执行 | `execute_prepared_run` → `_claim_acg_execution` → 正式派发门禁/运行 fence → ACG Scheduler → 调用前再次验证 Permit | 测试通过已有路径执行，HTTP 控制入口不执行 |

本轮生产修改仅 `apps/agent/app/api/agentos_c2.py`。`apps/agent/tests/test_agentos_c2_http.py` 仅将服务线程的清理改为 `await aclose_runtime(runtime)`；原 11 项测试及安全断言保留。新增 `apps/agent/tests/test_agentos_c2_permit_http.py` 与本报告。`agentos_v2.py`、Coordinator、wiring、核心 Authority、Store、Schema 均保持任务 A 后源码不变。

实现及测试 Commit：`ab6adb4042f4dd26a3358f8b254dc0c53893aa1f`，标题 `feat(agentos-c2): 接入图状态交接与执行许可HTTP控制`。报告独立归档，避免在报告正文中自引用自身 Commit SHA；报告归档 Commit 可用 `git log -1 --format=%H -- docs/audits/PR-C2B-INT-2B-2.md` 精确取得。

## HTTP 接口与响应

均要求已验证的服务端身份上下文及当前 Mission write 权限。`expectedGraphId` / `expectedGraphVersion` 是对既有持久 Head 的比较条件，不能构造 GraphVersion。请求模型 `extra=forbid`。

```http
POST /agentos/v2/missions/<mission-id>/runs/<run-id>/graph/handoffs
Content-Type: application/json

{"operationId":"handoff-1","activationId":"<activation-id>","expectedGraphId":"<graph-id>","expectedGraphVersion":1}
```

```json
{"operationId":"handoff-1","status":"STATE_PREPARED","handoffId":"<handoff-id>","graphVersion":1}
```

```http
POST /agentos/v2/missions/<mission-id>/runs/<run-id>/graph/permits
Content-Type: application/json

{"operationId":"permit-1","handoffId":"<handoff-id>","expectedGraphId":"<graph-id>","expectedGraphVersion":1}
```

```json
{"operationId":"permit-1","status":"ISSUED","permitId":"<permit-id>","runId":"<run-id>","graphVersion":1}
```

重放为 `IDEMPOTENT_REPLAY`，正式 ID 保持相同。拒绝采用 403/409/422；存储或 ACK 中断返回 503 并要求重试原操作。响应只含公开状态和引用，不返回候选执行状态、staged/promoted checkpoint 内容或 ID、principal fingerprint、内部签名、package checksum 或敏感来源审计字段。

继续使用可信 tenant/actor/action/Mission/Run 作用域 operationId 的散列 key。相同作用域 key 不能换绑其他来源；不同 key 对同一来源竞争明确拒绝。Handoff 签发后首次重放仍由 Handoff Authority 验证；Permit 已 ISSUED 后，Handoff builder 因原 Run 已合法推进而不再满足 pristine 条件，因此 HTTP 仅在正式派发门禁通过且原 key 精确对应正式 Permit 的同一持久 Handoff 时，读取历史 `STATE_PREPARED` 回执返回重放，不再执行 stage/confirm。任何当前来源漂移仍拒绝，不创建第二套状态机或账本。

Permit Authority 的 ISSUED 重放本身是历史事实读取；HTTP 在暴露该回执前额外调用现有 `assert_dispatchable`，避免将已撤权或来源变化的历史许可当成可继续使用的授权。PREPARING 恢复继续交给原 Authority，不直接改 Run 修复。

## 正式状态投影

已有 `GET /agentos/v2/runs/<run-id>` 的 `formalControl` 增加：

```json
{"status":"ACTIVATED","handoffId":"<handoff-id>","handoffStatus":"STATE_PREPARED","permitId":"<permit-id>","permitStatus":"ISSUED","permitIssued":true,"dispatchEligible":true,"executionAuthorized":true}
```

- `permitIssued`：持久 Permit 已完成 ISSUED 的历史事实；PREPARING 永远为 false。若历史许可撤销，不能由此推导可派发；损坏的证据链可使查询保守返回 503。
- `dispatchEligible`：当前读取通过正式 `assert_dispatchable`、已确认执行操作检查，Run 在门禁读取后未变且没有活动执行 slot，才返回 true；当前 Authority 缺失或证据/权限/来源无法可靠证明时为 false。它是读取时的门禁结果，不是未来的执行保证。
- `executionAuthorized`：保留兼容字段，严格等于 `dispatchEligible`，不再由 Permit 投影非空推断。
- `status=ACTIVATED_PAUSED`：尚无正式 ISSUED Permit；Handoff 为 STATE_PREPARED 或 Permit 为 PREPARING 也不改变此边界。ISSUED 后为 ACTIVATED，Run lifecycle 的取消/失败/完成状态仍在原字段中显示。
- 取消、终态、当前 Mission revision 变化、write 权限撤销、来源/Identity/checkpoint 漂移和 Authority 解绑均不展示可派发。查询不对账、不写状态、不签发许可、不启动 Scheduler。

Workflow Head、Handoff、Permit 历史事实在一个 SQLite 读取事务中取值；跨库实时门禁随后交给已有权威验证，不声称这次跨库读取是单个事务。继续保留 C2 开关关闭后对既有 PAUSED 状态的查询兼容。

## 测试证据

HTTP 夹具使用 TestClient 服务 lifespan 装配真实生产 Runtime，并在同一服务线程 `await aclose_runtime`。仅离线业务 Agent/模板和 Planner 策略为确定性夹具，关键 Authority、SQLite 事务、Checkpoint promotion 和 Identity 写入均真实执行。故障注入在真实写入后丢失 ACK 或使用临时数据库 trigger 中断最终 ISSUED 事务。

新增 15 项（含参数化实例）覆盖：

- 完整 HTTP 链、无 Handoff / 无 Permit / 伪造 Permit 拒绝、正式门禁允许后的真实 Runtime 节点执行、再次执行无重复副作用、重启后验证及回执重放。
- 当前 Head、Mission/Run/GraphVersion 错误，跨用户/租户，principal/Identity/Checkpoint/执行收据等额外字段拒绝；相同 key 来源换绑及竞争 key 拒绝。
- staged checkpoint 实际落盘后 ACK 丢失；Handoff confirmation 事务回滚；checkpoint promotion 实际提交后 ACK 丢失；Identity 实际提交后 ACK 丢失；Workflow ISSUED trigger 失败。
- 上述五种中断均验证零节点执行、PREPARING 不授权，并重构服务用原 key 收敛。重放比较 Workflow、Checkpoint、Identity、执行值数据库所有业务表，确认不新增重复事实。
- ISSUED 后 Run 取消、正式终态化、Mission revision 改变、当前 write 权限撤销、未确认 checkpoint、工作流来源修改、Identity 持久映射删除及 Permit Authority 解绑，均区分历史签发与当前派发资格。

最终 API 合并门禁：**102 passed, 3 warnings in 103.67s，退出码 0**。包括原 HTTP 11 项、新增 HTTP 15 项和既有认证/控制/API/装配/Coordinator 76 项。此前两部分分别通过：26 passed in 84.11s、76 passed in 22.51s，退出码均为 0，不重复累计测试数。

实际 pytest 子命令（仓库根目录）：

```powershell
python -m pytest apps/agent/tests/test_agentos_c2_http.py apps/agent/tests/test_agentos_c2_permit_http.py apps/agent/tests/test_internal_service_auth.py apps/agent/tests/test_agentos_control_contracts.py apps/agent/tests/test_agentos_v2_api.py apps/agent/tests/test_execution_runtime_application_wiring.py apps/agent/tests/test_execution_coordinator.py -q --disable-warnings --maxfail=1
```

这次命令由 Python `subprocess.run` 驱动，运行前后逐文件计算 SHA256，输出 `API_EXIT_CODE=0`、`SOURCE_SNAPSHOT_UNCHANGED=True`；快照如下：

| 文件 | 前后一致的 SHA256 |
| --- | --- |
| `apps/agent/app/api/agentos_c2.py` | `737ae56a4de8d0d04d6aa27bd30891b126440f3b81c2fb3e8fdbe88acf89d34e` |
| `apps/agent/app/api/agentos_v2.py` | `50bae5369cc91bf29fbf62e005ba850bd095087523d3e2bd4b4bc058973a15b6` |
| `apps/agent/app/execution/coordinator.py` | `bc246c57782b1bdf99affea219c612d1ab2ae0fd9a6138f9e0f385866a9e9647` |
| `apps/agent/app/execution/wiring.py` | `f4bf4a611b5939a880bf7819b1665264ad3319d0b452f3ad2a1ef08e4b4f4d23` |
| `apps/agent/tests/test_agentos_c2_http.py` | `7046e066bf0b3e4c6179bd3edb629d67e0321341c6a2bcb86898af3c99887972` |
| `apps/agent/tests/test_agentos_c2_permit_http.py` | `4b483b22671e8ca3b1f42f84cce07930d737708c7ea0ebed6c4b25766eab3850` |

核心 C 组子命令（cwd 为 `apps/agentOS`，通过驱动子进程将 `AGENT_CHROMA_PATH` 与 13 个 `AGENTOS_*_DB` / `AGENTOS_WORKFLOW_DB_PATH` 默认路径指向 `.tmp-tests/c2b2-core-*` 临时目录）：

```powershell
python -m pytest tests/components/planner/test_graph_handoff.py tests/components/planner/test_graph_handoff_recovery.py tests/components/planner/test_execution_permit.py tests/components/planner/test_execution_permit_audit.py tests/components/planner/test_initial_execution_permit.py tests/components/planner/test_permit_recovery.py tests/components/planner/test_permit_recovery_final_audit.py -q --disable-warnings --maxfail=1
```

该集合未过滤已有 `slow_multiprocess` 或 `slow_fault_injection` 标记，最终结果 **145 passed in 495.23s，`CORE_EXIT_CODE=0`**；不包括 `test_graph_handoff_gate.py` 的大 DAG 性能 benchmark。整个相关门禁为 API 102 项 + 核心 145 项，均实际执行通过。`git diff --check` 通过，测试后再次校验六个源码快照一致，未发现新的 P0/P1。

初次 HTTP 测试的 503 来自新接线使用同步路由导致 Checkpoint 连接跨服务线程使用，是本轮 API 实现问题；改为 async 路由在服务线程调用原 Authority 后，15 项新增测试及原 11 项通过。未以修改 SQLite `check_same_thread` 或 mock Authority 掩盖问题。

初次核心命令从仓库根目录启动，在第一个 fixture 内旧子进程 helper 按 cwd 拼出错误 PYTHONPATH，出现 `ModuleNotFoundError: test_react_loop`，退出码 1（1 error），不是生产合同失败。修正启动目录为 `apps/agentOS` 后，以临时目录隔离环境默认数据路径重跑原集合，未修改核心测试或生产实现。

## Git、推送与生产限制

既有 `mirror` 远程有 GitHub 与 Gitee 两个 push URL，本授权仅涉及 GitHub，不执行会同时推送两个站点的 `git push mirror`。GitHub `master` 只读核实为 `aebab1f76281837050fef54e698b1662a8419159`。工作区存在上述并行文档删除，按用户推送策略停止推送，不强推、不覆盖、不合并、不更改远程配置。

实现提交后再次执行 `git ls-remote --heads https://github.com/zongxi-Li/zhiyi-AgentOS-2026.git refs/heads/master`，退出码 0，远程仍为上述 SHA。报告归档后本地 `master` 包含任务 A 固化、B2 实现测试和本报告归档三个提交；最终工作区仅保留 ` D docs/audits/审计汇编-中文.md`，暂存区为空，本任务无遗留未跟踪文件。不以 tracking ref 的 ahead 显示替代远程核实。

未修改前端、compose 或生产开关；没有生产 Schema 升级、部署、真实业务数据写入；未执行无关全量 pytest，也未清空冻结门禁耗时缓存。

剩余限制及 INT-2C 入场条件：

1. 正式 HTTP Scheduler 提交入口仍缺失。INT-2C 需设计受控 dispatch 命令及其幂等、并发、取消、重启恢复合同，再决定如何与 Coordinator 集成；不能把 permitIssued 或一次 dispatchEligible=true 直接当成执行命令。
2. 新 Handoff/Permit 调用依赖 Runtime 所属服务线程，验证期间同步工作可能占用事件循环（P2/P3 性能边界）；未来优化必须先处理资源生命周期和线程归属，不直接搬入 worker 线程。
3. 许可失效或证据损坏时，投影保守返回 dispatchEligible=false，严重持久证据损坏返回 503。REVOKED 的独立持久撤销工作流及运营修复面不在本轮新增范围。
4. 本轮支持的正式执行拓扑仍受已有 Initial / DAG Authority 合同限制；不扩大控制节点、迁移或 Scheduler 框架。
5. 大 DAG 性能基准不是本次 HTTP 功能门禁；没有据此给出新的性能承诺。
6. 独立复验通过、用户并行改动处理完毕及推送前重新核实远程无推进后，才具备后续远程同步条件。

完成后停止，不进入 INT-2C。本报告最终状态只取 SELF-TESTED 或 BLOCKED，等待独立复验。
