# PR-C2B-INT-2C：正式 Dispatch 与生命周期恢复闭环

日期：2026-10-25。工程状态：**SELF-TESTED**，等待独立验收，不宣告独立 ACCEPT。

## Git 入场与 INT-2B 冻结

入场本地 master 与 GitHub master 均为 `28623c1b634b33d9edb289a7b641294db296cf00`；暂存区、工作区及全部未跟踪文件为空。已确认 `b0ea6c88c80754588a98679f6fc813646d3b4b4a`、`ab6adb4042f4dd26a3358f8b254dc0c53893aa1f`、`01a9ac574fce7b3aeb49b63972ba9a63ab417977` 在分支历史中。`28623c1b` 的文档删除保留，不恢复。

INT-2B 独立源码验收结论 `ACCEPT WITH LIMITATIONS` 已作为独立文档提交：`959612e0f146b4f31d99d32ae5e8fc451b558be3`，文件 `docs/audits/PR-C2B-INT-2B-FREEZE.md`。只修改冻结记录，未改已验收实现。102 项 API、145 项核心合同的既有证据明确标为继承证据；本轮新鲜结果单列。

本轮实现/回归 Commit：`8aad3ef2c18e70e2999f47bd6958221509d22a79`，标题 `feat(agentos-c2): 接入持久派发与安全生命周期恢复`。报告独立归档；为避免自引用，其归档 SHA 使用 `git log -1 --format=%H -- docs/audits/PR-C2B-INT-2C.md` 精确取得，并在最终交付消息中给出。

## Dispatch 接线矩阵

| 层次 | 实际调用及持久事实 | 本轮变化 |
| --- | --- | --- |
| HTTP | `POST /agentos/v2/missions/{mission_id}/runs/{run_id}/execution/dispatches` | 可信用户/租户及当前 Mission write 权限检查，只有持久引用和预期版本；不裸调用 Runtime 执行 |
| Coordinator | `submit_permitted()` | 与原 `submit()` 分离；协调锁 → Run 锁 → 同一 OS Run fence → 正式门禁 → 不可变命令 COMMIT → 受管 Task |
| 最终执行复验 | `execute_prepared_run` → `reconcile_execution_checkpoint` → `_claim_acg_execution` → `assert_dispatchable` / `assert_settled_operations` | 保持原代码及最终复验；没有第二套 Runtime、Permit Authority 或 Scheduler |
| Native Scheduler | ACG execution service / node runner / 调用前 Permit guard | 仍唯一执行节点，生成真实节点操作、审计、输出、Checkpoint 和 Artifact |
| 取消/失败 | `runtime.cancel` / `fail_run_safely` / Native invocation guard | 沿用原生命周期；Dispatch 重放不重新激活取消、失败、完成或审核暂停 Run |
| 重启恢复 | Coordinator 只扫描已接受命令，再调用已有 `reconcile_execution_checkpoint` 和 Permit 门禁 | 无命令的 Permit Run 不入队；证据不充分用原生命周期服务记录 `dispatch_recovery_blocked`，不伪造收据 |

原 `submit()` 的 pending/started_at/retrying 条件未放宽。开启 Dispatch 功能后，已有正式图的 retrying Run 还必须有已接受命令，才可通过专用受控路径恢复；普通 Legacy 路径保持原条件。启动时不再把正式图的 retrying 标记当成无条件自动工作。

## 最小持久扩展及复用不可行证据

审计当前 `SQLiteWorkflowStore`：

- `save_prepared_run_once` / `find_run_by_idempotency_key` 是创建 Run 的幂等合同；复用会将 Dispatch 与 Run 身份混为一体。
- `save_copilot_exchange` 只按 `(run_id, operation_id)` 插入会话内容，列表用于 Copilot 展示，没有每个 Run 唯一 Dispatch 拥有者或正式准入复验合同。
- lifecycle outbox 由 Identity 投影消费，不能把未知 Dispatch 命令伪装成身份生命周期事件。
- 普通 Run trace/可变 execution_state 不能提供独立不可变准入回执；仅靠 Task 字典也不能证明崩溃前是否接受命令。

因此新增 `SQLiteExecutionDispatchStore`，只在现有 Workflow SQLite 中保存：

- `execution_dispatch_schema(version=1)`。
- `execution_dispatch_commands`：Run 主键、可信作用域 operation key 唯一、版本化 payload、checksum。

payload 记录 Dispatch ID、请求摘要、Mission/Run/Permit/Graph 引用、预期 Runtime revision、服务端已验证 actor/tenant 及接受时间。没有 RUNNING/RECOVERING 等第二套状态字段；实际生命周期及最终结果由现有 Run、Checkpoint、NodeExecution 和审计决定。

每个 Run 只接受一个不可变命令。相同 key + 相同请求摘要返回同一事实；相同 key 换绑引用/版本拒绝；不同 key 竞争同一 Run 拒绝。SQLite `BEGIN IMMEDIATE` 和主键约束为持久竞争边界。新命令在该事务内再次调用现有派发门禁；OS fence 与 Runtime 最终执行复验仍负责排除执行竞争和提交后漂移。

显式管理入口：

```powershell
python scripts/upgrade_agentos_dispatch_schema.py --workflow-db <existing-C2-workflow.sqlite> --apply
```

未传 `--apply` 时只验证。必须先存在完整 C2 schema；构造 Store 和服务启动只验证版本及 SQL 定义，不创建或升级 Dispatch 表。新增服务装配选项 `AGENTOS_C2_EXECUTION_DISPATCH` 默认 false；设为 true 必须同时启用原 C2 authorities，并已显式安装 version 1。未知版本、缺失 schema、损坏命令拒绝启动或准入。该选项只在临时测试环境启用，没有修改生产开关、配置或真实数据库。

## API 请求与回执

```http
POST /agentos/v2/missions/<mission-id>/runs/<run-id>/execution/dispatches
Content-Type: application/json

{"operationId":"dispatch-1","expectedPermitId":"<issued-permit-id>","expectedGraphId":"<graph-id>","expectedGraphVersion":1,"expectedRuntimeRevision":2}
```

预期 Runtime revision 以最新 Run 查询为准，示例中的 2 不构成固定版本承诺。请求模型 `extra=forbid`；principal、Permit Record、Checkpoint、executionState 等不能由客户端上传。

```json
{"operationId":"dispatch-1","dispatchId":"<dispatch-id>","runId":"<run-id>","permitId":"<issued-permit-id>","graphVersion":1,"status":"ACCEPTED","runStatus":"planning","errorCode":null}
```

响应 202 表示命令已持久接受，不表示节点已执行。原请求重放为 `IDEMPOTENT_REPLAY`、同一 Dispatch ID，并返回当前 Run 状态；终态重放只读取原事实，不再次入队。当前 write 权限仍先校验。回执不返回内部 actor/tenant、指纹、Checkpoint 正文、签名或凭据。

冲突/无许可/过期版本/生命周期不适用为 409，身份权限错误为 401/403，额外字段为 422，存储或 ACK 中断为 503。Permit ISSUED、STATE_PREPARED 或一次 dispatchEligible=true 都不是 Dispatch 命令。

原 Run 查询继续区分 `permitIssued` 与 `dispatchEligible`；本轮补充审核暂停时不可派发。Dispatch 原事实可用同 operationId 重放查询，Run lifecycle、错误和内容继续通过现有 GET 查询。

## 崩溃、取消与恢复策略

| 切点 | 恢复/阻断策略 | 验证 |
| --- | --- | --- |
| Permit ISSUED，无命令 | 启动只保留许可，不创建执行 Task | 重构真实 Runtime 后零节点调用 |
| 命令 COMMIT 后、Task 前 | 原记录保留，启动恢复已授权意图，重新经当前门禁和 Checkpoint 对账 | 实际子进程 `os._exit(73)`；重启后 A/B/C 各一次 |
| Task 创建后 HTTP ACK 丢失 | 同 key 读取原事实，当前 Task 不重复创建 | 故障注入后回执 ID 相同、节点无重复 |
| 原 key、命令已接受、Task 创建失败 | 同 key 可在安全门禁后补建受管 Task；不同 key 不接管 | COMMIT 后异常 + 原 key 重放 |
| A 已完成且新 Checkpoint 提交后进程死亡 | 现有 Permit Recovery 验证审计/执行/身份/Checkpoint 事实并确认投影，然后继续剩余节点 | 实际子进程 `os._exit(75)`；重启只执行 B/C，外部 A 记录恰一次 |
| A 外部副作用已发生，但未有足够执行证据 | 禁止自动重放；通过现有 `fail_run_safely` 持久记录 FAILED / `dispatch_recovery_blocked`，保留未结清操作 | 实际子进程 `os._exit(74)`；重启零节点调用，外部记录仍只有 A |
| 取得 Native 槽后取消 | 原取消信号及调用前 guard 阻止节点调用，原终态不可重启 | Native claim 后调用正式 cancel，零 Agent 调用 |
| Dispatch 与 cancel 竞态 | 最多一个准入事实；取消和最终派发复验决定 Run 状态 | 并发 HTTP 请求，取消后不执行 B、不被重放激活 |
| 提交前 Mission / Permit / Graph / 主体漂移 | 事务内重新调用正式门禁，拒绝且不保存命令 | 错误引用/版本、撤权及准入边界真实 Mission commit |
| 审核暂停 | 命令重放保持暂停；必须走原正式审核接口 | 高风险业务输出触发 Auditor，原请求不推进；批准后 B/C 完成 |
| Provider 失败或不确定的安全关闭 | 不把重放当作补跑命令；已失败终态保留，未结清调用在启动恢复中阻断 | 确定性失败 Agent、真实 Task cancellation、重构后零重复调用 |

允许恢复的依据是原已接受的显式命令及现有权威证明，不是单纯发现 Permit。恢复身份仅从已接受的服务端命令恢复 actor/tenant 上下文，不保存服务 token，也不把历史角色当成新的权限；当前 semantic write 权限和 Permit principal fingerprint 每次复验。

关闭时不把被打断的已许可 Task 无条件伪装为 worker_shutdown 终态；保留事实交由已有 Recovery 判定。取消用户请求仍保留 CANCELLED。无法证明无副作用时，宁可阻断；没有跨数据库原子提交或任意远端非幂等副作用 exactly-once 承诺。

## 真实 E2E 与代码自审

主链使用 FastAPI TestClient、生产装配、真实 Authority 和临时 SQLite。业务测试工作流包含 A/B 的合同事实处理与 C 的 artifact_generation；只替换确定性业务 Agent/Planner，未 mock Scheduler、Permit 或数据库事务。证明了：Dispatch 前调用次数 0；Dispatch 后 A/B/C 各一次；三个真实 committed NodeExecution、审计 allow 记录、同 Permit 的 Checkpoint、最终 Artifact 与 Run 内容查询；终态原请求及重启后的重放不重复执行。

代码级自审结论（最终相关门禁均已通过）：

- 不可变准入记录不是第二套执行/恢复状态机。所有实际节点仍经过 Native Scheduler、Permit 复验及调用前 guard。
- 新准入持有 Run 锁、OS fence 和 Workflow 写边界；Runtime 保留最终复验。进程内 Task 只是 Coordinator 的资源所有权，不是持久回执。
- 同 key 活动/终态重放不会争抢 Native fence 或新建第二执行者；不同 key 在读取既有命令后即冲突。
- 取消、终态、审核暂停不会被 replay 重新激活。未结清操作、Checkpoint 或身份不一致不会被直接修改 Run 以“修复”。
- 真实服务关闭验证受管 Task、watch Task 和 execution slots 清空，且同一目录可重构 Runtime；实例锁和资源由现有 `aclose_runtime` 回收。
- 没有前端、compose、Gitee、生产配置或真实数据库变更。

## 定向门禁与源码摘要

最终 API 合并命令（仓库根目录，由 Python subprocess 驱动并记录前后 SHA256）：

```powershell
python -m pytest apps/agent/tests/test_agentos_c2_dispatch_http.py apps/agent/tests/test_agentos_c2_http.py apps/agent/tests/test_agentos_c2_permit_http.py apps/agent/tests/test_internal_service_auth.py apps/agent/tests/test_agentos_control_contracts.py apps/agent/tests/test_agentos_v2_api.py apps/agent/tests/test_execution_runtime_application_wiring.py apps/agent/tests/test_execution_coordinator.py -q --disable-warnings --maxfail=1
```

最终核心/生命周期命令（cwd=`apps/agentOS`，subprocess 环境默认 DB/Chroma 路径隔离在 `.tmp-tests/c2c-core-*`；未过滤已有多进程或故障标记）：

```powershell
python -m pytest tests/components/planner/test_graph_handoff.py tests/components/planner/test_graph_handoff_recovery.py tests/components/planner/test_execution_permit.py tests/components/planner/test_execution_permit_audit.py tests/components/planner/test_initial_execution_permit.py tests/components/planner/test_permit_recovery.py tests/components/planner/test_permit_recovery_final_audit.py tests/components/planner/test_production_authority_assembly.py tests/runtime/test_fault_recovery.py tests/runtime/test_review_recovery_extraction.py -q --disable-warnings --maxfail=1
```

最终 API：**123 passed, 4 warnings in 423.31s，`API_EXIT_CODE=0`，`SOURCE_SNAPSHOT_UNCHANGED=True`**。包括新增 Dispatch 21 项、原 HTTP 26 项及其他 API/认证/装配/Coordinator 76 项。

最终核心/生命周期：**164 passed, 1 warning in 719.45s，`CORE_EXIT_CODE=0`**。所选 Authority、Permit Recovery、生产装配及生命周期集合全部实际执行，没有过滤已有慢故障/多进程标记。两组共 287 个定向测试实例通过，未运行无关全量 pytest。`git diff --check` 与新增文件 UTF-8/空白检查通过，提交前再次核对源码快照。

已完成的定向诊断：原 HTTP 26 项通过（141.15s），Coordinator/认证/控制/装配 24 项通过（9.44s）；新 Dispatch 前 11 项通过（106.40s）；新增进程退出三个切点及 claim 后取消已通过；审核/竞态/关闭/失败/准入漂移/损坏拒绝六项通过（64.58s）。这些是过程验证，不重复累加到最终计数。

曾出现并已修正的测试问题：审计 Store 从调用者线程读取造成 SQLite 线程异常，改在服务线程读取；子进程缺少 `apps/agentOS` 路径导致 service 模块导入失败，补齐测试 PYTHONPATH；Initial plain-DAG 不调用所假设的 Planner 暂停 hook，改用真实 Auditor 高风险输出触发审核。没有为修复夹具降低安全断言或修改 Authority。

最终 API 命令前后相同的源码 SHA256：

| 文件 | SHA256 |
| --- | --- |
| `app/api/agentos_c2.py` | `c032cbd2ea12e84550f665341ab60df3c324060b3905d12fff75879f65d99282` |
| `app/api/agentos_v2.py` | `89575880a15f42b8845931cb7ef6cdea975f3ee34447cf8b3e925fb37afaa04b` |
| `app/execution/coordinator.py` | `c71498d3c9fcd03bf7ecac118e469ff1ff88c582b731810bd09909266d812f3e` |
| `app/execution/wiring.py` | `ae33e10b745ec8db86ffb6753b7bf20d9a01f6eb8a01b502455a0b0a622971b7` |
| `support/stores/execution_dispatch_store.py` | `6c7dbeb3ad6de787ab53439ba4175825740f6b7502706e58d8ec953cca758a09` |
| `scripts/upgrade_agentos_dispatch_schema.py` | `9ce88afae5fa3f756801da50539425783977a785f5cabcde62ca6f69dcd66d49` |
| `tests/test_agentos_c2_http.py` | `64e9ef3ba2dd7d23a5a0ce81afee5a6874f1d19708881678f065a685ac042a75` |
| `tests/test_agentos_c2_dispatch_http.py` | `52ca88da7dd56155cc678b9536a6a2a697d10d50cc17e2c0ac7006056d880a43` |

## 限制及 INT-2D 入场条件

- P0/P1：代码级自审未发现新增安全缺陷；相关定向门禁均通过，等待独立验收。
- P2：version 1 每个 Run 只允许一个 Dispatch 意图。失败后的新业务尝试应走原正式 Recovery / successor Run 合同，不允许更换 operationId 越过原失败或审核边界。
- P2：仍是单 Runtime / 原目录实例锁部署，非分布式租约队列。大规模历史命令扫描、同步 SQLite/权威验证占用服务线程等性能问题未在本轮扩展处理。
- P2：生产保持新开关关闭；上线前必须在离线副本验证备份、现有 C2 Schema 与显式 Dispatch version 1 升级，不能把测试临时库升级等同生产迁移验收。Dispatch 使用独立显式升级入口，未扩大基础 C2 schema orchestrator 的扩展识别/安装合同。
- P2/P3：不确定外部副作用的人工处置和运营恢复面不在本轮自动化；证据缺失会保守 FAILED / dispatch_recovery_blocked，不作盲目恢复。
- P3：前端应保留原 operationId，或后续补充只读 Dispatch 发现投影；不能因 Permit 已签发、dispatchEligible=true 或收到 202 就假定节点已执行完毕。
- INT-2D 前置：独立验收后消费正式 Dispatch API、稳定 operationId、Run lifecycle、审核/取消、恢复阻断和 Artifact 引用；区分“准备许可 / 明确派发 / 执行中 / 等待审核 / 完成 / 阻断”，不直接构造执行授权或修改核心状态。

完成后停止，不进入 INT-2D；未执行无关全量 pytest、未清空冻结门禁历史缓存、未升级真实业务数据库或部署。

## 最终 Git 与 GitHub 核实

入场基线 `28623c1b634b33d9edb289a7b641294db296cf00` 是最终分支祖先；本轮只增加冻结记录、实现与回归、验收报告三个职责清楚的提交。代码 SHA 为上述 `8aad3ef2...`，最终 master HEAD 为本报告归档提交，工作区和暂存区干净，没有遗留未跟踪交付文件。

提交前再次 `git ls-remote` 核实 GitHub master 仍为 `28623c1b634b33d9edb289a7b641294db296cf00`。仅通过明确 GitHub URL 推送 `HEAD:refs/heads/master`，不调用有两个 push URL 的 `git push mirror`，不修改或推送 Gitee，不强推、不隐式合并。

交付核实以以下三步为准，最终确切远程 SHA 同时记录于交付消息（等于报告归档 HEAD，避免提交正文自引用）：

```powershell
git merge-base --is-ancestor 28623c1b634b33d9edb289a7b641294db296cf00 HEAD
git push https://github.com/zongxi-Li/zhiyi-AgentOS-2026.git HEAD:refs/heads/master
git ls-remote --heads https://github.com/zongxi-Li/zhiyi-AgentOS-2026.git refs/heads/master
```

若推送期间远程出现非预期推进，则停止推送并在交付消息报告阻断，绝不以覆盖远程解决。报告中的 SELF-TESTED 是工程自测状态，不替代独立验收或生产部署许可。
