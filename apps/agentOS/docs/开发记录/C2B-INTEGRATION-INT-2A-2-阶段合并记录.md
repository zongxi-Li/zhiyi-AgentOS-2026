# C2B-INTEGRATION-INT-2A-2-阶段合并记录

> 本文按阶段归档三份开发记录，正文原样保留；原文件已合并移除，以下文件名仅作来源标识。

## 原始记录目录

- `C2B-INTEGRATION-INT-2A-2-生产装配最终独立验收.md`
- `C2B-INTEGRATION-INT-2A-2-FIX-异步取消清理修复记录.md`
- `C2B-INTEGRATION-INT-2A-2-GATE-CLOSEOUT-最终冻结门禁收束.md`

---

<!-- 原始记录：C2B-INTEGRATION-INT-2A-2-生产装配最终独立验收.md -->

# PR-C2B-INT-2A-2：生产 Authority 装配最终独立验收

验收日期：2026-10-25（Asia/Shanghai）。最终判断：**REJECT**。

已证实一个 P1：生产默认异步 Runtime 关闭函数在客户端清理的 await 点收到取消后，跳过剩余资源及实例锁释放，且锁仍被标记为有效。既有冻结门禁通过不能覆盖这一缺口；当前不得冻结，也不进入 INT-2B。本轮只审查、实验和出具文档，没有修复生产代码。

## 1. 实际 Git 基线与源码摘要

- 入场实际 HEAD：`ff06464edb68d77bac1e0df38dc772a140032f24`，与任务声明完全一致。这是本地对象核验，不代表重新认证 GitHub 远端引用。
- 入场 `git status --short` 为空；`git diff --stat`、`git diff --cached --stat` 均为空。不存在需要归因的暂存、未暂存或未跟踪业务改动。
- 收尾生产代码未修改；暂存区为空，`git diff --check HEAD` 退出 0。仅新增本验收文档，实验材料保存在被忽略的 `tmp/int2a2/`。
- 当前 AgentOS `src/tests` 共 454 个 Python 文件，聚合 SHA-256：`4e3dd7457b57faffb5e65819703abab8834feb537e5212a46b6c40adf0e831a8`。门禁前后逐文件快照及外部文件快照一致，补充实验后再次核验。
- 固定入场 manifest：`scripts/freeze_gate_baselines/c2b-int1-entry.json`；SHA-256 `54ccc02a3d0ba550fffff8dd23f259460977ae0a75f3d8eea4d7c1848ce1a591`，445 个文件、聚合 `cb5809b8a2e29278d39d6ab70c6bd1567da7073148195201d013f1105f9a2c47`。这是门禁历史比较基准，不是当前 HEAD。

当前原始文件字节摘要（含 Windows 行尾）：

| 文件 | SHA-256 |
| --- | --- |
| `apps/agent/app/main.py` | `f086ec71a00d5cb305fc6d68c34494bca011bc991b7d658caf4a400d4c56757d` |
| `apps/agent/app/lifespan.py` | `1e4f5e7cabfd5df60ed8a7d3deb1ccd5e72b3f59499e6389ff01a422ced19b01` |
| `apps/agent/app/api/agentos_v2.py` | `2127e6e7065db1ca7179b6c5a805bb4c73d2868d5adba12431c2d76d3abe14e3` |
| `apps/agent/app/execution/wiring.py` | `2d4f8e7c3bd98550a613cb039c392bb1a96e4ed91a26ce5e1725a44defa924cf` |
| `apps/agent/app/execution/instance_lock.py` | `b52efb5e1fd6c193ffb63734f3e10bf83597277dbe5992bce59deb7a1b7ff757` |
| `scripts/freeze_gate.py` | `51dd6aad04bfcba5ec3464ce974a18beb0d24116693728ea0ffbc7afc82d059f` |
| `scripts/freeze_gate_pytest_runner.py` | `68736bccd5b3cfaf0fbbd02a800ef23b12d03c269c471e4693a11ca77a8345ef` |
| `scripts/upgrade_agentos_c2_schema.py` | `72b55f01379900c658391cb110d142fa7de126f4d9dbea0c3d076b82c3cb08cd` |
| `apps/agent/app/execution/coordinator.py` | `bc246c57782b1bdf99affea219c612d1ab2ae0fd9a6138f9e0f385866a9e9647` |
| `apps/agentOS/src/runtime/workflow_runtime.py` | `7d2a314f692a5e1243deb28be7e0f694d611c7389fc9ed79beffe141581420fe` |
| `apps/agentOS/src/runtime/acg_execution.py` | `c046088a4d26d235c2e3d7dc0c850a1fbe35fcfae67f577569593a7d7ad083d8` |
| `apps/agentOS/src/runtime/execution_permit.py` | `84c4df8ad1c9bcdec4d7910cd699b632cf81f7a3d3d424cdcf41111296fcffa1` |
| `apps/agentOS/src/runtime/permit_recovery.py` | `058e0ec37ee449e09e69216a653b86cccd6781c4cdfd8ef2fd5e68d49b868a67` |

`before.json` 保留完整 454 文件清单、外部摘要、19 条选择路径及入场缓存摘要。Coordinator 属本轮额外审查文件，当前摘要和 Git 内容已核对，但不在现有门禁的外部运行中快照内，见 P2-02。

## 2. 正式生产链与五类 Authority 接线矩阵

源码链为 `apps/agent/app/main.py:42` 构造 Runtime，随后创建 `RunExecutionCoordinator(runtime)`，并将 Runtime、ModelSetup、Coordinator 注入 `build_lifespan`。`build_default_runtime` 解析开关、取得实例锁、构造三库及基础资源，在创建唯一 `ExecutionRuntime` 后依次装配五类 Authority，再进行 Identity 对账与 Native runtime 注册。没有导入执行 `app.main`，避免打开真实默认数据库。

| 顺序 / Authority | 正式装配入口与 Store | 实际绑定、校验与执行边界 |
| --- | --- | --- |
| 1 Planning Commit | `wiring.py:533`，`enable_planning_commit(SQLitePlanningCommitStore(...))` | 路径来自 `runtime.workflow_store.db_path`；构造校验 planning schema marker、记录/outbox 表；只接受规划事实，不签发 Permit。 |
| 2 Graph Materialization | `wiring.py:534`，`SQLiteGraphMaterializationStore` | 与 Planning Commit 和 Workflow 同库；校验 marker、表结构；仅持久化 `MATERIALIZED_INACTIVE`。 |
| 3 Graph Activation | `wiring.py:537`，`SQLiteGraphActivationStore` | 要求上游 Materialization 与 Workflow 一致；校验 activation schema；在 Workflow 单库事务内切换 Head 与 Run，停在 `ACTIVATED_PAUSED`。 |
| 4 Graph Handoff | `wiring.py:538`，`SQLiteGraphHandoffStore` + `SQLiteStagedGraphCheckpointStore` | 前者使用 Workflow 库，后者使用 `runtime.checkpoint_store.db_path`；构造要求 staged=Checkpoint 且不等于 Workflow；只形成 `STATE_PREPARED`。 |
| 5 Execution Permit | `wiring.py:542`，`SQLiteExecutionPermitStore` | Workflow 同库且 Handoff 已装配、Checkpoint 路径匹配；校验 permit marker/表结构；通过 PREPARING saga 和最终 Workflow 提交形成 ISSUED。 |

Store 使用 `mode=rw` 的逐操作连接，构造验证已有 Schema，不隐式调用 C2 升级。Materialization、Activation、Handoff、Permit 的构造互验顺序及库路径；临时库缺失 Schema 会中止启动。基础 Runtime Store 的既有建表行为与 C2 Store verify-only 应分别理解，不能把整个启动过程称作完全只读。

正常关闭资源序列包含基础 Store、Identity 生命周期、异步 transport，以及五类 Authority Store（含 staged Store）；按对象身份去重，Authority Store 当前无常驻连接。`_AssemblyProgress` 在 Runtime 构造前记录已拥有资源，普通装配异常清理失败不会替换原始装配异常。**异步取消清理不满足上述生命周期合同，见 P1-01。**

## 3. Legacy 与 C2 隔离、执行授权合同

| 开关组合 | 实际生产行为 |
| --- | --- |
| semantic=false，C2=false | 五类 Authority 均 None；未升级临时库可继续走既有 Legacy 执行，无隐式 C2 DDL。 |
| semantic=false，C2=true | 在实例锁及资源构造前抛错，不隐式开启语义收敛。 |
| semantic=true，C2=false | 仅既有语义路径；不装配五类 Authority。 |
| semantic=true，C2=true | 要求可信 principal、已有语义及完整 C2 Schema；缺失即启动失败。 |

`workflow_runtime.py:626` 在 Planning Commit Authority 存在时强制 deferred planning，调用者传入 `defer_acg_planning=False` 也不能让新 ACG Run 走直接物化捷径；新 Run 写入 `planningCommitRequired`。正式装配测试验证 Initial acceptance 零节点调用，物化、激活后仍无许可，执行入口拒绝；显式 Handoff 与 Permit 后才执行 A/B/C。

`_claim_acg_execution` 先取得跨进程 Run fence，再在同一 Workflow 读事务中读取最新 Run、调用 `validate_activation_run`。已有持久化 Head 时，缺失/错误投影不会降级为 Legacy；即使未挂 Permit Authority 也拒绝。通过 Permit 验证及操作收据恢复屏障后才认领执行槽。此处保护已采用 C2 的 Run；不能解释为给所有升级前历史 Run 自动补发许可。

`ExecutionPermitAuthority.assert_dispatchable` 及 `_assert_dispatch_authority` 要求正式记录 ISSUED、投影相等、Run/Activation/GraphVersion/执行 generation 一致、Run 未取消/终态、当前 principal 和语义授权有效、Identity 和已确认 Checkpoint 一致。资源分配前后、节点派发前以及 Adapter invocation 前再次验证；Coordinator 仅拥有后台任务，不拥有发证权，最终仍调用 `execute_prepared_run` 和 Native Scheduler 的资源绑定路径。

本轮门禁实际执行 `test_execution_permit.py` 9 节点（含 paused 拒绝、正式 Permit 后 Native 派发、principal 撤权拒绝、checkpoint/Run 漂移拒绝）与正式装配 3 节点。对取消、迟到 Identity 漂移、错误 generation/GraphVersion 的更细边界，复核了 `test_initial_execution_permit.py`、`test_execution_permit_audit.py`、`test_permit_recovery.py`、`test_permit_recovery_final_audit.py` 的既有反例及对应源码；**这些文件未在本轮 295 节点选择集中，不冒充本轮重跑结果**。本轮未发现执行许可绕过的失败反例，也不宣称对所有历史故障切点做了新一轮穷举。

## 4. 启动、关闭、恢复与补充实验

| 合同 | 本轮证据及结论 |
| --- | --- |
| 正常启动、关闭、再次启动 | 正式装配测试及 cleanup 测试通过；同一组临时库可重建，已完成节点不会因再次调用执行入口或启动恢复而重复执行。 |
| 五类 Authority 中途失败 | cleanup 测试对五个 enable 步骤逐一注入普通异常，验证资源关闭、锁释放及原始异常；25 节点门禁通过。 |
| 持久化部分完成后重建 | 既有生产装配测试含重建和 PREPARING 恢复，但其 PREPARING 注入发生在重建之后，不能单凭该段宣称“此切点后重建”；因此新增下述一个必要实验。 |
| PREPARING 后真实重新装配 | 临时库执行到 Handoff，`save_promoted` 抛错后确认 PREPARING/零节点调用；关闭 Runtime，再经同一 `build_default_runtime` 重新构造，以原幂等键恢复 ISSUED，随后 A/B/C 各执行一次。补充测试通过。 |
| completed prefix / 未解释外部操作 | 生产恢复测试验证 completed Run 重建后零重复，未解释执行 operation 阻断；Permit Recovery 源码只允许已确认收据与 Workflow 前缀，不合成外部成功。 |
| lifespan 默认依赖 | `test_app_lifespan.py` 18 节点实际通过，默认闭包动态导入并 await `wiring.aclose_runtime`；main 注入与默认依赖测试均核对。 |
| 真实异步关闭被取消 | 两个新增参数场景均失败，证实 P1-01；外层 lifespan 继续下一层清理不能补救 Runtime 内部已跳过的资源。 |

补充命令（工作目录 `apps/agentOS`）：

```powershell
python -m pytest -c pytest.ini ../../tmp/int2a2/test_final_boundary.py -q --tb=short
```

实际结果：**2 failed, 1 passed, 1 warning in 32.84s**，进程退出 1。首次启动实验漏传 `-c pytest.ini`，因外部测试路径未加载项目 pythonpath，3 个用例均在 import contracts 阶段失败（0.84s），未进入 Runtime；原始输出保留为 `boundary.initial-import-error.log`。只修正实验启动命令后重跑，未改生产源码或清空缓存。

### P1-01 最小失败反例

位置：`apps/agent/app/execution/wiring.py:680-702`，尤其 `await aclose()` 的 `except Exception` 及循环后的锁释放。`asyncio.CancelledError` 不被此捕获；没有 finally 保证剩余资源及锁的清理。

反例复用现成 `test_production_authority_assembly` 的 `prepared_folder` / `composition_env`，只在临时三库显式升级；开启 C2 和语义收敛，正式装配本地 HTTP transport（环回占位地址，无远端请求）。将该真实 transport 的 `aclose` 替换为可控 await 以确定取消切点，使用真实 `Task.cancel()`，不是伪造锁释放或只对空 Runtime 测试：

```python
async def blocked_close():
    entered.set()
    await asyncio.Event().wait()
runtime.local_runtime_transport.aclose = blocked_close
# build_lifespan(runtime=runtime, ...) 保留默认 runtime_close。
task = asyncio.create_task(drive_real_lifespan())
await entered.wait()
task.cancel()
try:
    await task
except BaseException:
    pass
# 应已释放锁、关闭其余 Store；实际两者均未发生。
assert instance_lock._LOCK_HANDLE is None  # 实际失败
```

| 观测 | 正常服务关闭收到取消 | 启动原始异常后的关闭收到取消 |
| --- | --- | --- |
| 向调用方传播 | `CancelledError` | `RuntimeError`，仍是原始异常对象 |
| `_LOCK_HANDLE` 仍存在 | true | true |
| `_LOCK_VALID` 仍为 true | true | true |
| 同库 `acquire_workflow_instance_lock` 复用旧句柄 | true | true |
| Checkpoint 连接 `SELECT 1` 仍成功 | true | true |
| HTTP client 已关闭 | false | false |

这是生产清理和失败后再次装配的 P1 合同违例：取消可发生在实际客户端关闭 await；其余库句柄和锁未释放，同库重试仍被有效锁状态放行。未声称它已造成跨主机执行、远端副作用重复或 Permit 绕过。实验 finally 恢复 transport 方法并再次调用真实关闭函数，两例均确认最终锁已释放，未把泄漏留在验收进程。

最小修复验收要求：Runtime 内部记录取消、继续尝试余下资源、在可靠收尾路径处理锁及失效状态，最后传播取消；启动 unwind 继续保留原始启动异常。对实际默认 closer 增加正常关闭/启动失败两条任务取消回归，而非仅在 lifespan 层注入一个抛 CancelledError 的 runtime_close 桩。本轮不实施修复。

## 5. P0 / P1 / P2 / P3 发现清单

| 编号 | 等级 | 发现及处置 |
| --- | --- | --- |
| P1-01 | P1，已证实 | 真实 Runtime async cleanup 取消泄漏资源并保留有效实例锁；两个最小失败反例。阻止 INT-2A 冻结。 |
| P2-01 | P2，后续工程 | max-per-node 历史耗时相加可超过预算并误阻断；同源码/同节点的 320.900s 历史预估与 191.718s、213.138s 实跑相矛盾。需记录环境和缓存代际，不以静默清缓存形成验收。 |
| P2-02 | P2，后续工程 | 生产 `app/execution/coordinator.py` 不在门禁 `EXTERNAL_SOURCES`，也不在 AgentOS src/tests 快照。仅修改该文件不会由现有差异映射触发测试，运行中漂移也不由门禁检测。本轮人工审查及独立摘要限定在当前内容；后续补充固定基线和对应 Coordinator 回归映射。 |
| P3-01 | P3，文档证据 | 旧 INT-2A-1 实施记录中的 244/155.653s、旧 wiring 摘要对应历史快照，不能代替本次 295/213.138s 和当前摘要；本报告予以明确区分，不修改历史记录。 |

未发现已证实的 P0。P2/P3 本身不构成无限期阻断受限交付的理由；本次 REJECT 仅由 P1-01 决定。

## 6. 冻结门禁实际结果、清单和基线认证

本轮正式门禁只执行一次，默认 **300 秒**，未缩减选择、不改安全标记、不扩大排除、不执行全量 pytest。北京时间 2026-10-25 15:39:25 至 15:42:58；门禁 **PASSED**，进程退出 0，pytest 退出 0，未超时，完整墙钟 **213.138s**；pytest 自身 **295 passed, 2 warnings in 204.28s**。这只说明既有选择通过，不能覆盖新增反例。

入口等价执行 `python scripts/freeze_gate.py`：外层 Python `runpy.run_path(..., run_name='__main__')` 保持默认 argv，设置 `PYTHONUTF8=1`，将唯一发现读取进程环境的通信库 `AGENTOS_COMMUNICATION_DB` 指向 `TemporaryDirectory`；正式装配测试其余库由已有 tmp_path fixture 指定。没有设置或修改持久生产开关、compose 或真实库路径。

- 19 条选择路径与入场 `resolve_tests` 计算逐项相等；收集为 295 个唯一节点。
- `.nodeids` 295 行与收集清单逐项相等，SHA-256 `ce6f9a18e9098b88f6d9cc4d74c2341d27cc87d6f5ce542fd9102aa5a8db5d7f`；执行命令使用 `freeze_gate_pytest_runner.py` 读取这一清单，命令长度 228 字符。
- runner 在进程内将完整清单传给 `pytest.main`，直接返回 pytest 退出码；不分批、不按文件替换、不截断。integrity 用例实际测试短命令的成功路径与不存在节点的非零退出路径。
- 本轮 295 passed、0 skipped/deselected，与 295 唯一选择节点一致；日志中正耗时节点是该清单子集，亚毫秒阶段会隐藏。没有独立逐节点事件账本，因此不以 `pytest_counts.collected=null` 宣称收集失败或额外补造执行清单；采用清单传递实现、runner 对抗测试、总数与无 deselect 共同核对。
- `uncovered_source_paths`、`missing_test_paths`、`missing_external_source_paths` 均空。固定 manifest 的字节 SHA、445 文件 aggregate 认证成功，未退回 HEAD 建新基线。
- 外部 main/lifespan/wiring/instance_lock/runner 摘要与固定值一致；API、gate 自身及新增升级 CLI 相对固定基线的差异按现有映射触发测试，不等同于“所有外部文件无差异”。
- 门禁前后 `source_snapshot` 完整字典和 `external_snapshot` 相等，状态未触发 SOURCE_CHANGED；补充实验后仍相等。Coordinator 的快照盲区按 P2-02 单列。

实际各测试文件节点数：

| 测试文件 | 节点数 |
| --- | ---: |
| `tests/adapters/test_model_runtime_streaming.py` | 8 |
| `tests/components/planner/test_execution_permit.py` | 9 |
| `tests/components/planner/test_production_authority_assembly.py` | 3 |
| `tests/components/resource/test_edge_cloud_contracts.py` | 9 |
| `tests/components/resource/test_health_store.py` | 2 |
| `tests/components/resource/test_node_store.py` | 14 |
| `tests/components/resource/test_remote_observation.py` | 9 |
| `tests/components/resource/test_resource_auth.py` | 12 |
| `tests/components/resource/test_store_contract.py` | 16 |
| `tests/components/scheduler/test_binder.py` | 18 |
| `tests/components/scheduler/test_redis_leases.py` | 9 |
| `tests/runtime/test_app_lifespan.py` | 18 |
| `tests/runtime/test_contract_review_delivery.py` | 36 |
| `tests/runtime/test_kernel_vertical_slice.py` | 3 |
| `tests/storage/test_c2_schema_integrity.py` | 24 |
| `tests/storage/test_c2_schema_upgrade.py` | 40 |
| `tests/storage/test_freeze_gate_integrity.py` | 39 |
| `tests/storage/test_runtime_assembly_failure_cleanup.py` | 25 |
| `tests/storage/v2/test_schema.py` | 1 |

原始证据：`tmp/freeze_gate/20261025T073930Z.json`、`.log`、`.nodeids`；日志 SHA-256 `74149ed335a4378c1945fbf0af3683ea73c8826a250df02913db5a7cacce37f5`。独立核对结果 `tmp/int2a2/gate-check.json`，完整 stdout `gate.stdout.log`。新增对抗测试在门禁结束后执行，未计入 295 节点；停止冻结后未尝试第二次门禁制造通过结论。

### 历史耗时缓存审计

入场缓存原样复制到 `tmp/int2a2/test_durations.before.json`，SHA-256 `d036c34ae116bb4e422800394d1e59ed6f9bbc9e8f6405942f1086288a18049f`。本轮既未删除、清空，也未替换原缓存；仅由门禁正常按 max 规则更新。

当前缓存 200 条；本次 295 个选择节点中 200 条已知、95 条未知，已知和 **183.570s**，预算预检通过。既有本地证据同时显示：

1. `20261025T044850Z.json`：同一当前 source aggregate、295 节点，已知和 **320.900s**，剩余 **297.151s**，`BLOCKED_KNOWN_DURATION_OVER_BUDGET`，pytest 未启动。这是一次真实阻断，不能抹去。
2. `test_durations.json.pre-remediation2.bak` 有 463 条，对相同 295 节点求和仍为 320.900s。
3. `20261025T045031Z.json`：当前 source aggregate 与全部外部摘要均相等，清单仍为 295，历史已知和变为 **0** 后实际 **191.718s** 通过；之后入场缓存为 200 条、所选和 183.570s。可确认缓存历史发生了重置/替换效果，不能仅凭这些文件判定具体操作人或删除命令，也不能把此前阻断改记为通过。
4. 本轮保留缓存实跑 213.138s 再次通过。固定节点及安全覆盖不变，这支持“累加不同运行中各节点最大值产生环境观测误阻断”，**没有证实不可满足的覆盖/300s 冲突**；也不保证所有环境都可满足预算。

## 7. 数据库、安全边界及生产部署限制

| 库 | 生产配置实际来源 | 本轮边界 |
| --- | --- | --- |
| Workflow | 必填 `AGENTOS_WORKFLOW_DB_PATH` | 五 Authority 主 ledger 与 Run/Head 使用同一路径；只以临时库实验，不解析或打开真实业务库。 |
| Checkpoint | `AGENTOS_LANGGRAPH_CHECKPOINT_DB`，默认相对路径 `data/langgraph_checkpoints.sqlite3` | Handoff staged 与 Runtime checkpoint 取同一实例路径；独立于 Workflow；测试显式指向 tmp_path。 |
| Identity | `AGENTOS_IDENTITY_DB`，否则 Workflow 同目录 `identity_v2.sqlite3` | 同一 lifecycle/repositories 服务参与授权和恢复；实验使用临时 identity.sqlite，不对真实库运行 preflight/apply。 |

三库路径的绑定与分离已从正式 wiring 和构造互验核对；这不意味着三个数据库共享联合原子事务。Permit 是可恢复的 PREPARING/ISSUED saga，Checkpoint/Identity 与最终 Workflow 提交存在中断窗口，必须用原幂等键收敛，不能用盲重试忽略持久事实。

以下限制继续成立，不能因本地测试通过而标为已解决：

- **不存在跨数据库联合原子事务。**
- **本地撤权不能自动撤销远端已经开始的副作用。** 调用前复验只是新的派发屏障，无法替代远端取消、幂等或补偿合同。
- **多主机执行一致性尚未验收。** 单进程/同机文件锁及既有 Redis 测试不等同于多主机端到端一致性。
- **真实生产 Schema 升级及业务数据库 READY 未确认。** 临时三库 READY 仅用于测试准备，不作生产 READY 证据。

未访问或修改真实业务数据库，未执行真实升级 CLI/apply；未修改 compose、生产开关、HTTP 或前端；未新增 Authority、Store 或状态机；未提交、推送、合并或部署。

## 8. INT-2B 入场条件与停止点

1. 先在独立、明确授权的修复任务中修复 P1-01，将本报告两条真实 closer 取消反例纳入正式回归；正常关闭传播取消，启动失败保持原始异常，剩余资源和实例锁均完成清理或明确失效，失败状态不继续授权装配。
2. 对修复后的准确 Git/source baseline 重新验收；在未扩预算、未削减安全覆盖且保留缓存来源的条件下完成一次 300s 门禁，准确登记清单、实际退出码、运行中摘要和新增反例结果。当前旧选择的绿灯不能替代这一条。
3. 持续登记 P2 缓存观测策略与 Coordinator 门禁快照覆盖；它们可作为有限后续事项，不把它们扩大为新 Authority 或长期架构重构。
4. INT-2B 若涉及真实数据库或部署，必须另行确认备份、维护窗口、真实三库预检/升级与 READY，以及拟启用的执行范围；本报告不提供升级或生产开关授权。若涉及远端副作用或多主机，需独立合同与验证证据。

**最终：REJECT。已停止冻结；本轮结束，不自动进入 INT-2B。**


---

<!-- 原始记录：C2B-INTEGRATION-INT-2A-2-FIX-异步取消清理修复记录.md -->

# PR-C2B-INT-2A-2-FIX：Runtime 异步取消清理修复记录

日期：2026-10-25（Asia/Shanghai）。P1-01 已完成限定修复，原始及永久反例由红转绿。正式冻结证据仍不完整；保留本次结果，不重跑门禁、不清空缓存，不宣称可冻结。

## 基线和范围

入场及收尾 HEAD 均为 `ff06464edb68d77bac1e0df38dc772a140032f24`。入场暂存区和 tracked diff 均空，仅有前轮未跟踪的独立验收报告；已使用并保留该文件，字节 SHA-256 未变。未提交或推送。

本轮仅修改：

- `apps/agent/app/execution/wiring.py:680`：修复 `aclose_runtime` 的取消与收尾合同。
- `apps/agentOS/tests/storage/test_runtime_assembly_failure_cleanup.py:485` 起：复用既有临时三库和正式装配 helpers，新增 5 个永久回归节点。
- `scripts/freeze_gate.py:141`：更新 wiring 固定摘要及修复任务注释，以满足已有 integrity 合同；测试映射、原始 manifest、300 秒预算和安全排除逻辑均未调整。

`lifespan.py`、`instance_lock.py` 均未修改；没有新增 Authority、Store、Schema、运行状态机或平行资源管理器。当前独立报告的历史 REJECT 不由本修复记录擅自覆盖。

## 生产处理合同

`aclose_runtime` 分别记录普通异常与第一个 `asyncio.CancelledError`，对每个资源独立尝试关闭；后续再次取消仍被记录并继续清理。资源身份去重不变，锁释放置于 finally。锁 helper 在 OS 操作之前清除 `_LOCK_VALID`，释放失败时保留无效清理引用；真实组合测试确认重新装配拒绝该状态。

收尾后优先传播取消，普通错误逐条保留日志，并在取消异常附注数量；无取消时仍抛第一个普通关闭错误。生产 lifespan 默认 closer 的正常关闭会传播取消，启动失败 unwind 保留原始异常对象；无需修改 lifespan 的既有优先级合同。

**被取消的客户端并未被宣称成功关闭。** 显式 warning 标明 `resource may remain open; retry shutdown explicitly`；Runtime 保留已有 owned 引用，不自动重试、不 shield、不建立后台清理任务。正常调用方收到取消；启动失败路径记录清理取消但继续传播原始启动异常。需要在宿主存活时显式再次关闭，或由进程退出回收 OS 资源；测试 finally 恢复注入方法后显式重试，验证客户端最终关闭。此策略不声称撤销已经发生的远端副作用。

## 红绿与永久回归

| 证据 | 实际结果 |
| --- | --- |
| 原始 `tmp/int2a2/test_final_boundary.py` 两个真实 Task.cancel 反例，修复前 | 2 failed、1 deselected，27.68s，退出 1；正常关闭和启动失败 unwind 都留下有效锁与未关闭 Checkpoint。 |
| 整理到正式模块的同两例，生产代码修复前 | 2 failed、28 deselected，26.21s，退出 1。 |
| 修复后首轮定向 | 100 passed、1 failed，91.98s；唯一失败是新增重建测试未保持资源凭据主密钥，导致临时库凭据解密失败；修正 test helper 参数及测试前置条件，未扩展生产修复。 |
| 修正前置条件后定向回归 | 101 passed, 1 warning in 180.15s (0:03:00)；退出 0。 |

定向集合包括 cleanup 模块 30、lifespan 18、Execution Permit 9、正式生产 Authority 装配 3、freeze integrity 39，以及原始 tmp 反例 2，共 **101 节点**。五类 Authority 装配中途异常、正常/重复关闭、同进程重建、Permit 授权、重启恢复和 Legacy 行为均包含在此集合。

新增永久节点验证：

1. 默认 lifespan 的正常关闭和启动失败各一次，正式 C2 Runtime 的真实 transport await 收到真实 Task.cancel；后续 Checkpoint 连接确实关闭，旧锁句柄关闭且 `_LOCK_VALID=False`，重新获取得到不同句柄；启动错误保持对象身份。客户端中断状态和 warning 同时断言。
2. 两次真实 Task.cancel 分别命中 transport 和后续异步 closer，同时注入两个普通 Store 关闭错误；另以参数注入锁释放失败。确认两次取消不吞掉、所有故障被记录、后续 Store 关闭；锁释放失败时状态无效且正式重新装配被拒绝。
3. 普通异步/同步关闭异常组合仍继续释放资源，显式重试可关闭中断客户端，重复异步关闭及持同一测试加密键重新装配正常。

原 tmp 探针的 `same_database_lock_reused` 字段表达式在“新获取句柄”时也会返回 true，不能用它证明修复后仍复用旧句柄。永久用例保留 old_handle 并断言 `old_handle.closed` 和 `fresh is not old_handle`，弥补此观测歧义。原始红态 JSON 已另存，未用绿态覆盖历史证据。

复现命令、原始输出与退出码保存在 `tmp/int2a2-fix/`：`red-original.log`、`red-permanent.log`、`focused-first.log`、`focused.log` 及相应 `.exitcode.txt`；原始红态锁观测为 `audit-cancellation-False.json` / `audit-cancellation-True.json`。`focused-first.log` 对应一次临时测试前置条件失败，未隐去。

## 唯一一次正式冻结门禁

由 `tmp/int2a2-fix/run_gate.py` 以子进程执行真实命令 `python scripts/freeze_gate.py`，保留默认 **300 秒**；隔离 `AGENTOS_COMMUNICATION_DB` 至 TemporaryDirectory，其余装配库沿用既有 tmp_path fixture，不打开真实业务库。

- 状态：**INCOMPLETE_TIMEOUT**；门禁实际退出码 **1**；pytest 实际退出码 `1`；完整墙钟 **300.657s**，`timed_out=True`。
- 本次是实际运行超时，不是历史耗时预检阻断；pytest 子进程被预算终止，所记录的退出 1 不能解释为正常完成后的断言失败汇总。300.657s 含进程树终止与报告收尾，测试预算未放宽。定向两轮的 91.98s 与 180.15s 也显示耗时明显波动，但没有证据确定其系统原因或保证下次运行可满足预算。
- 选择路径 19；收集唯一节点 300；清单行数 300；passed `None`。未形成完整成功执行数量证据，不能认证全部选择节点已完成；只以原始退出码、timeout 和日志记录实际终止情况。实际 pytest 观测保存在 JSON/log，不以已收集数量冒充已执行数量。
- 节点清单与 collected IDs 逐项一致、清单摘要一致；短命令仍从 manifest 读取原节点列表，未截断或降为按文件启动，runner 退出码直接来自 pytest。`-q` 输出不提供独立逐节点事件账本，计数与清单传递路径分别核对。
- 固定 manifest 字节和 aggregate 认证通过；`uncovered/missing_test/missing_external` 为空；外部 wiring 摘要与本轮固定值一致。
- 门禁源码前后及收尾再次核验一致；AgentOS src/tests **454 文件**，聚合 `cb4a3124a214e8793f2ea018836ac1d963a5cf753946d6d0f9afbc4e9a42bc26`。本轮修改被包含在此准确快照内，未在测试期间继续修改源码。

报告：`tmp\freeze_gate\20261025T080259Z.json`；原始 stdout `tmp/int2a2-fix/gate.stdout.log`；独立清单/摘要/退出码核对 `gate-check.json`，前后完整快照为 `gate-before.json` / `gate-after.json`。

缓存执行前原样备份为 `tmp/int2a2-fix/test_durations.before.json`，203 条，SHA-256 `68b4bdf9f85fef63640e482fa823ec12036d41c6c9eaa18643db0762ded7a3fa`；所选节点历史已知和 **213.64s**，未知节点 97。本轮没有删除、清空或替换原缓存，仅允许门禁正常追加最大观测值。此前 320.900s 预检阻断、463 条旧备份与后续重置效果的证据均保留，来源摘要登记在 `cache-provenance.json`；不将旧阻断改记为通过，也不拿旧的 295 节点绿灯替代本轮门禁。

## 收尾与限制

`git diff --check HEAD` 退出 0（仅 gate 文件 LF→CRLF 提示，无 whitespace 错误）。暂存区为空。所有实验使用临时 SQLite，未访问真实业务数据库、未升级生产 Schema、未修改 HTTP/前端/compose/生产开关；未运行全量 pytest，未提交、推送、合并或进入 INT-2B。

本轮已执行回归未发现新增 P0/P1；取消清理合同的定向证据已转绿，是否冻结仍等待最终独立确认。P2/P3 的缓存观测、Coordinator 门禁覆盖和历史文档差异继续作为技术债，本轮不扩展修复。

| 收尾文件 | SHA-256 |
| --- | --- |
| `apps/agent/app/execution/wiring.py` | `f4bf4a611b5939a880bf7819b1665264ad3319d0b452f3ad2a1ef08e4b4f4d23` |
| `apps/agentOS/tests/storage/test_runtime_assembly_failure_cleanup.py` | `5170123fe8b9a14ac6c180b94e95b15ba2bdc994fa7ef88372aaf0f2075a7818` |
| `scripts/freeze_gate.py` | `af9ff6d92d4e85f723e749db091a71d01565baaea06ad569ef416c09b8657f69` |
| `apps/agent/app/lifespan.py` | `1e4f5e7cabfd5df60ed8a7d3deb1ccd5e72b3f59499e6389ff01a422ced19b01` |
| `apps/agent/app/execution/instance_lock.py` | `b52efb5e1fd6c193ffb63734f3e10bf83597277dbe5992bce59deb7a1b7ff757` |
| `apps/agentOS/docs/开发记录/C2B-INTEGRATION-INT-2A-2-生产装配最终独立验收.md` | `b45bd176325b41aff46419f8d029d0598f826ccfb9c43b491dd868280051a014` |


---

<!-- 原始记录：C2B-INTEGRATION-INT-2A-2-GATE-CLOSEOUT-最终冻结门禁收束.md -->

# PR-C2B-INT-2A-2-GATE-CLOSEOUT：最终冻结门禁收束

日期：2026-10-25（Asia/Shanghai）。正式冻结证据已收束，P1-01 五个永久回归在正式门禁内全部通过；最终源代码差异已备齐供独立验收。

## Git 与变更范围

HEAD 仍为 `ff06464edb68d77bac1e0df38dc772a140032f24`，暂存区为空。入场已有 P1-FIX 的三项 tracked 修改（wiring、cleanup 测试模块、freeze_gate 固定摘要）与两份未跟踪验收/修复文档，全部保留。本轮**未修改生产代码、永久测试、fixtures、Schema、开关、测试标记或门禁代码**；仅增加本报告及 tmp 诊断/运行证据。

所有入场代码摘要保持一致。最终相对 HEAD 的生产修复差异：`tmp/int2a2-gate-closeout/final-source.patch`，SHA-256 `b99cdb865d552d54044926eecfbf0098ea5407515fb8948a3449879d13f62e09`。它包含前轮 P1-FIX 已授权差异，不代表本轮又修改 Runtime。未提交、推送、部署或进入 INT-2B。

## 原超时的可确认位置与缓存

`20261025T080259Z.json` 是 `INCOMPLETE_TIMEOUT`，300 秒硬预算，墙钟 300.657s；日志有 294 个成功进度点，清单有 300 个唯一节点。runner 按清单顺序传给 pytest，因此可定位至第 295 项 `test_real_lifespan_cancelled_runtime_close_releases_resources[False]` 附近：前 294 项已有成功标记，第 295 项及后续没有完成标记。旧日志没有逐节点 start/call 事件，**不能进一步确认该项内部停止位置或证明后六项均已执行**。

旧预检的 203 条历史记录对所选节点求和 213.640s，预检通过，实际 pytest 已启动。故这次不是历史缓存阻断，是实际运行变慢。入场缓存 SHA-256 `68b4bdf9f85fef63640e482fa823ec12036d41c6c9eaa18643db0762ded7a3fa`；本轮执行前原样备份，未清空、删除或替换，旧备份及原超时材料未改动。

## 耗时诊断与对照

采用 `-vv --durations=0`、逐测试 cProfile，仅运行新增 5 节点和已识别慢的 3 节点；所有真实 Runtime、临时三库、Task.cancel、Store 关闭、实例锁及异常断言保留。

新 5 节点在上一轮 focused.log 的 call 耗时依次为 **8.97、11.81、9.75、9.44、14.83s**。本轮同代码函数级剖析发现：

- 前四项各创建一个正式 Runtime、执行一次临时三库升级。每项的 `load_verify_locations` 调用 4 次，合计约 **8.17–8.35s**；`aclose_runtime` 累计仅 **0.020–0.032s**，Schema upgrade 约 **0.245–0.468s**。
- 普通关闭/重建项必须创建两次 Runtime；CA 装载 8 次、**17.445s / 总 18.997s**，两次 Schema upgrade 合计 **0.406s**。第二次 helper 重复准备 Schema 确实存在，但占比很小，不是本次主要瓶颈，未为此改写 fixtures。
- 既有 `test_adversarial_async_shutdown_closes_transport_in_owning_loop` 从旧 focused-first.log 的 7.52s 增至 focused.log 的 17.59s；本轮剖析 17.809s，其中 8 次 CA 装载占 **17.244s**。它真实创建 owned 与 borrowed HTTPX 客户端，断言合同未变。
- 两个既有生产装配项也增长：Initial 从 4.71s 增至 9.14s，重启恢复从 12.33s 增至 25.99s。本轮主线程剖析约 12.04s / 27.61s；代理隔离后约 10.57s / 29.58s，**没有显著改善，不能将其额外耗时全部归于代理或 SSL**。

安装的 HTTPX 源码显示客户端按环境代理构造 transport/SSL context；测试进程原继承 HTTP_PROXY、HTTPS_PROXY、ALL_PROXY（三者仅记录存在性，不记录值）。CA 文件 236095 字节，证书校验默认开启。只在子进程移除这三个变量（含大小写变体）后，真实客户端每个只装载一次同一 CA；没有 mock、缓存 SSLContext、跳过证书校验或改变生产配置。

同一 8 项的对照：**8 passed / 117.57s → 8 passed / 62.06s**，均退出 0。5 个新增项 call 合计 **55.967s → 13.734s**。逐项 cProfile call 时间（含剖析开销，不当作生产延迟）：

| 节点 | 继承代理 / s | 隔离代理 / s |
| --- | ---: | ---: |
| `test_real_lifespan_cancelled_runtime_close_releases_resources[False]` | 9.684 | 1.788 |
| `test_real_lifespan_cancelled_runtime_close_releases_resources[True]` | 8.960 | 1.449 |
| `test_repeated_runtime_close_cancellation_with_errors_is_fail_closed[False]` | 8.999 | 1.713 |
| `test_repeated_runtime_close_cancellation_with_errors_is_fail_closed[True]` | 9.327 | 3.077 |
| `test_async_close_errors_continue_and_normal_close_rebuilds` | 18.997 | 5.707 |
| `test_adversarial_async_shutdown_closes_transport_in_owning_loop` | 17.809 | 4.797 |
| `test_restart_recovery_restores_authorities_without_implicit_dispatch` | 27.611 | 29.576 |
| `test_initial_execution_requires_permit_through_production_assembly` | 12.043 | 10.571 |

该对照确认了环境代理带来的重复 CA 装载是新增回归和 owned/borrowed 客户端测试的主要开销；单次 CA 装载时间本身也有波动，其系统原因未证实。没有证据据此断言 CPU 降频、杀毒扫描、全机过载或 SQLite 竞争。入口未见遗留 Python 测试进程；采样可用物理内存约 10GB、CPU 占用约 17%/32%（不同采样时刻），均不能回推此前门禁的机器负载。

正常剖析没有显示 5 秒故障等待到期或资源关闭阻塞，SQLite execute 累计远小于 CA 装载。额外尝试工作线程剖析仅留下 40 秒主线程事件循环等待栈，无完成统计/退出码；后续未见其进程，实验不完整，**不计入通过/失败数量，也不当作 Runtime 缺陷或已定位的线程死锁证据**。未为此继续扩大架构调查或修改业务代码。

证据为 `tmp/int2a2-gate-closeout/profile.log`、`profiles.json`、`case-*.prof`、`direct-profile.log`、`direct/profiles.json`、`thread-profile.log`、`diagnosis.json`。仅代理隔离这项已通过对照的环境处理用于最终门禁。

## 唯一一次最终正式门禁

诊断后仅执行一次真实子进程命令 `python scripts/freeze_gate.py`；预算仍 **300 秒**，测试映射、安全标记、排除规则、节点清单均未修改。环境仅对该子进程隔离代理、将通信库放在 TemporaryDirectory，并加载只写事件日志的观察插件。观察插件不修改 items、测试方法、断言或退出码；发现阶段及嵌套 runner-integrity 单节点探针不写入正式事件账本。

- 实际状态：**PASSED**；门禁退出 **0**；pytest 退出 **0**；墙钟 **279.106s**，timeout=`False`。
- 19 条选择路径；收集 300 唯一节点，manifest 300 行，SHA-256 `840e5434fa6d228c99c7c84e5ad48468d6dab5af04db694e8d430efa5f45e709`。
- 实际 collection、start、call 事件分别 300 / 300 / 300；call 结果 `{'passed': 300}`；与 manifest 顺序逐项核对结果为 `True` / `True` / `True`。不以选中数量冒充完成数量。
- pytest 原始汇总 `{'passed': 300, 'failed': 0, 'error': 0, 'errors': 0, 'skipped': 0, 'xfailed': 0, 'xpassed': 0, 'deselected': 0, 'collected': None, 'not_completed': None}`。全部阶段结果 `{'passed': 900}`；session finish 记录在事件账本。新增五个永久回归在正式门禁中的结果及 setup+call+teardown 合计如下。

| 永久回归节点 | 实际结果 | 合计 / s |
| --- | --- | ---: |
| `test_async_close_errors_continue_and_normal_close_rebuilds` | passed | 5.294 |
| `test_real_lifespan_cancelled_runtime_close_releases_resources[False]` | passed | 2.817 |
| `test_real_lifespan_cancelled_runtime_close_releases_resources[True]` | passed | 2.690 |
| `test_repeated_runtime_close_cancellation_with_errors_is_fail_closed[False]` | passed | 2.786 |
| `test_repeated_runtime_close_cancellation_with_errors_is_fail_closed[True]` | passed | 2.754 |

- 固定 baseline 字节与 aggregate 认证通过；选择路径与独立 resolve 一致，uncovered/missing_test/missing_external 为空。
- 源码前后及收尾摘要一致：AgentOS src/tests 共 454 文件，聚合 `cb4a3124a214e8793f2ea018836ac1d963a5cf753946d6d0f9afbc4e9a42bc26`；全部外部文件快照一致，本轮代码相对入场无变化。
- 缓存原样备份 `test_durations.before.json`，正式预检已知和 **213.64s**、未知 97 项；仅由门禁正常更新最大观测值，原 203 条均保留且未降低。完成后所选节点历史最大值和 **287.600s**，不是本次实跑耗时。

原始报告：`tmp/freeze_gate/20261025T100534Z.json`，对应 log/nodeids 原样保留。精确执行账本 `tmp/int2a2-gate-closeout/execution.jsonl`；源码/清单/退出码复核 `final-check.json`；环境与单次启动脚本 `gate-environment.json` / `run_final_gate.py`。旧超时从未改写为通过。

## 收尾与剩余限制

`git diff --check HEAD` 通过，仅有已有 LF→CRLF 提示。暂存区为空；本轮新增报告与 tmp 证据，相对 HEAD 的三个修复文件仍未提交。没有改 HTTP/前端/compose/生产开关，没有访问真实业务数据库或升级生产 Schema，没有全量 pytest、提交、推送或部署。

本次证据属于上述明确隔离代理的离线临时库环境，不是任意机器负载/代理配置下都能小于 300 秒的性能保证，也不是生产 Schema READY、多主机一致性或远端副作用撤销验收。两项生产装配测试剩余耗时原因保留为后续观测事项，不借本轮扩大架构修复。到此停止，最终差异供独立验收，不自动进入 INT-2B。
