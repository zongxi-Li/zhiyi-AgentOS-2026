# C2B-INTEGRATION-INT-2A-1-阶段合并记录

> 本文按阶段合并开发记录。来源文档内容原样保留，原文件继续留在本目录。

## 原始记录目录

- `C2B-INTEGRATION-INT-2A-1-生产Authority装配实施记录.md`

---

<!-- 原始记录：C2B-INTEGRATION-INT-2A-1-生产Authority装配实施记录.md -->

# INT-2A-1：生产 Runtime 权威接线与装配级验证

日期：2026-10-23。阶段状态：**SELF-TESTED**。等待独立架构验收；不自行宣布 ACCEPT，不自动进入 INT-2B。

## 0. 宣称边界（先读这一段）

- **实现完成：是**（生产 Composition Root 已按开关接入五类 C2 Authority）。
- **测试通过：是**（定向回归 74/74；正式冻结门禁 PASSED 244/244，155.653 秒 < 300 秒）。
- **生产数据库已升级：否**（三库仍处 INT-2A-0 探测时的状态；本轮零真实库操作）。
- **生产部署已启用：否**（compose 与生产环境配置未动，两个开关在生产默认 false，legacy 直执行行为不变）。

## 1. 入场核验与并行修改保护

| 项 | 结果 |
| --- | --- |
| HEAD | `da11315470169b5e971170a83c7ef20b1128f75d`，与声明一致；master 领先 origin/master 1 笔（INT-1 冻结提交未推送） |
| INT-1 源码聚合 SHA-256 | `5ffb32c30c9835dcb5bf9e6166b1539c7dc44d4258a65d07d6ea4f5022e4a581`（451 文件），用 `freeze_gate.source_snapshot()` 复算精确匹配 |
| 暂存区 | 空（入场与收尾两次核验） |
| 并行修改保护 | 任务书列出的 5 项原样保留；入场时发现前端并行会话**新增**了 `apps/frontend/components.d.ts`、`package.json`、`package-lock.json`（M）与 `AcgExecutionFlow.spec.ts`/`AcgExecutionFlow.vue`/`AcgExecutionNode.vue`（未跟踪），同样全部保留，未覆盖、未暂存、未提交、未清理 |
| INT-2A-0 报告 | `apps/agentOS/docs/开发记录/C2B-INTEGRATION-INT-2A-0-生产装配入场审计与接线设计.md`（未跟踪，保留） |

入场基线与声明一致，无差异需要报告。

## 2. 实际修改文件与关键代码位置

| 文件 | 改动 | 关键位置 |
| --- | --- | --- |
| `apps/agent/app/execution/wiring.py` | +56 行 | 开关解析与联合校验（`build_default_runtime` 内，语义开关计算之后、Runtime 构造之前）；五权威装配块（`ExecutionRuntime` 构造与 attachment 赋值之后、identity 对账之前）；`close_runtime` 资源清单扩展 |
| `apps/agentOS/tests/storage/test_c2_schema_upgrade.py` | +110 行 | `test_c2_assembly_refuses_to_start_without_semantic_convergence`、`test_c2_assembly_fails_closed_when_schema_is_missing`、`test_c2_assembly_attaches_authorities_and_close_runtime_is_repeatable`；公共 `ENV_KEYS`/`assembly_env`/`role_paths`/`ScopedTools` |
| `apps/agentOS/tests/components/planner/test_production_authority_assembly.py` | 新增 296 行 | A/B/C 三组装配级测试（见第 5 节） |
| `apps/agentOS/tests/storage/test_freeze_gate_integrity.py` | +24/-1 行 | 外部源参数化纳入 wiring.py；映射表参数化纳入 wiring.py；`test_production_composition_root_is_pinned_and_drift_forces_assembly_tests` |
| `scripts/freeze_gate.py` | +5 行 | `SOURCE_TEST_RULES` 增加 wiring.py → 装配测试映射；`EXTERNAL_BASELINE` 增加 wiring.py 条目（摘要 `f69c1cbc…`，注释标明为 INT-2A-1 定稿内容） |

manifest（`scripts/freeze_gate_baselines/c2b-int1-entry.json`）**未修改**：外部源基线存于门禁脚本自身而非 JSON manifest，本轮机制不要求动 manifest；INT-1 历史基线及其 SHA-256（`54ccc02a…`）原样保留，integrity 测试第 108 行继续钉死该值。

预期外文件说明：无。前端与 drawio 的 9 个并行文件改动均属并行会话，与本轮无关。

## 3. 五类 Authority 装配顺序、数据库绑定与关闭行为

装配代码（`wiring.py`，开关开启时）：

```python
workflow_db_path = runtime.workflow_store.db_path
checkpoint_db_path = runtime.checkpoint_store.db_path
runtime.enable_planning_commit(SQLitePlanningCommitStore(workflow_db_path))
runtime.enable_graph_materialization(SQLiteGraphMaterializationStore(workflow_db_path))
runtime.enable_graph_activation(SQLiteGraphActivationStore(workflow_db_path))
runtime.enable_graph_handoff(SQLiteGraphHandoffStore(workflow_db_path),
                             SQLiteStagedGraphCheckpointStore(checkpoint_db_path))
runtime.enable_execution_permit(SQLiteExecutionPermitStore(workflow_db_path))
```

- 顺序即权威构造函数的互验依赖：Permit 要求 Handoff 已挂且三库路径等式成立；Handoff 要求 Activation 已挂且 staged 库=checkpoint 库、≠workflow 库；Activation/Materialization 逐级要求上游与 workflow 同库。乱序装配会在构造时抛错。
- Workflow 路径直接取 `runtime.workflow_store.db_path`（生产 Runtime 正在使用的库），staged 路径取 `runtime.checkpoint_store.db_path`——复用既有实例的路径对象，不做二次解析。
- 五个 Store 全部 verify-only（`mode=rw` 连接、构造校验 marker 表、无 DDL）。表缺失时的实际失败形态是 `sqlite3.OperationalError: no such table: planning_commit_schema`（构造即抛、不捕获、不降级），测试已按真实异常类型断言。
- 关闭行为：五个 Store 本为逐操作短连接（无持久句柄），`close_runtime` 仍将其纳入资源清单遍历（含 handoff 的 staged store），经既有 `callable(close)` 守卫与 `seen` 去重——未来 Store 若引入 close() 自动被覆盖。重复调用 `close_runtime` 已由测试验证安全。

## 4. 两个开关的组合合同与 fail-closed 行为

| `AGENTOS_MISSION_SEMANTIC_CONVERGENCE` | `AGENTOS_C2_EXECUTION_AUTHORITIES` | 结果 |
| --- | --- | --- |
| false（默认） | false（默认） | 现状：五权威未装配，legacy 直执行，零 C2 DDL（既有门禁测试 + 本轮 C 组测试锁定） |
| false | true | **启动抛 `RuntimeError`**（"AGENTOS_C2_EXECUTION_AUTHORITIES requires AGENTOS_MISSION_SEMANTIC_CONVERGENCE"），发生在 Runtime 构造之前；不自动开启语义收敛 |
| true | true | 装配五权威；语义层 S00-01 表必须已显式安装（`enable_existing_mission_semantics` verify-only），C2 表必须已显式升级，否则启动失败 |
| true | false | 仅语义收敛，行为同 INT-1 前的语义路径，无 C2 装配 |

不捕获 Store 构造异常、不隐式升级 Schema、不绕过语义 principal/owner/Identity/授权验证（测试通过生产 wiring 自带的 `authorize_semantics` 走完整所有权校验）。开关解析沿用 wiring.py 既有布尔风格（`str(env.get(...) or "false").lower() == "true"`）。

## 5. 测试场景、结果与耗时

全部 Runtime 经生产入口 `build_default_runtime(environment=...)` 构造（`syspath` 注入 `apps/agent`），数据库全部为临时测试库（`ops._initialize` + `upgrade_databases` 等价于 CLI 在测试库上的显式准备）。

**门禁扩展（test_c2_schema_upgrade.py，4/4 绿）**

1. 开关关：authority 全 None、无隐式 C2 DDL（既有测试，未改动）。
2. C2 开+语义关：`RuntimeError`，三库零 C2 表。
3. C2 开+schema 缺（S00-01 已装、C2 表缺）：`sqlite3.OperationalError/RuntimeError` 启动失败，无隐式 DDL（升级入口全部 monkeypatch 为显式失败，证明不是靠升级器通过的）。
4. C2 开+schema 全：五权威类型、`store.db_path == workflow 库`、`staged_store.db_path == checkpoint 库`全部断言；`close_runtime` 连续两次无异常。

**装配级测试（test_production_authority_assembly.py，3/3 绿，25.2s）**——业务工作流/Agent 复用 `examples/contract_review`，principal 经生产 wiring 注入缝替换（与 HTTP 边界盖章等价，所有权校验仍走 wiring 自带 authorize）；intent LLM 为失败桩+`deterministicIntent`，证明全程确定性规划零模型调用：

- **A 组 Initial 首次执行闭环**：语义 Mission → `execute_prepared_run`（Initial Commit 接受，Run 停 planningDeferred，零节点派发）→ `materialize_initial_commit`（MATERIALIZED_INACTIVE）→ activation prepare+commit（**ACTIVATED_PAUSED**，投影 `executionPermit=null`）→ **无 Permit 执行被拒**（ValueError）→ handoff（STATE_PREPARED）→ permit ISSUED；同键重放 IDEMPOTENT_REPLAY、同 handoff 换键 REJECTED；许可后整张 Initial 图恰好执行一次（A/B/C 各一次，3 张 committed 收据）；重复 `execute_prepared_run` 零重复执行。
- **B 组装配级重启恢复**：`close_runtime` 后用同一组库文件重新 `build_default_runtime`——历史授权从盘上恢复（ISSUED permit 可读、同键重放 IDEMPOTENT_REPLAY）；`close_orphaned_runs` 启动恢复**不派发 ACTIVATED_PAUSED Run**（状态不变、执行入口仍拒）；已完成 Run 重启后再执行零重复；PREPARING 中断态（checkpoint 晋升被打断 → 回执 STORAGE_UNAVAILABLE "reconcile with the original key"）以同幂等键重发收敛为 ISSUED 并真实可执行；已签发许可的 Run 在值库出现无法解释的 operation 时执行入口抛 "unexplained execution operations block Permit recovery" 且零派发。
- **C 组 Legacy 兼容**：独立未升级库 + 两开关全关：同构 Run 记录（无 graphActivation 投影）直接执行（compiledACGPackage 生成、节点真实执行），authority 全 None，workflow 库零 C2 表。该路径仅在开关关时可达；带 graphActivation 投影的 Run 在任何开关组合下都过不了执行认领——两种路径互不可冒充。

**门禁 integrity（test_freeze_gate_integrity.py，31/31 绿）**：wiring.py 进入外部源参数化与映射表参数化；`test_production_composition_root_is_pinned_and_drift_forces_assembly_tests` 断言（a）wiring.py 在 `EXTERNAL_SOURCES` 中且基线摘要==当前文件摘要（漂移必须伴随基线显式更新），（b）`resolve_tests([wiring.py])` 恰好映射到装配测试与 schema 门禁测试，（c）伪造漂移快照经 `changed_external_paths` 被标记并强制映射到装配测试。**"修改 wiring.py 必触发对应测试"由该测试机器化证明，另由 dry-run 实录佐证**（选择集含三个本轮测试文件、uncovered/missing 全空）。

定向回归合计：74 passed / 0 failed / 0 skipped（`test_c2_schema_upgrade.py` 40 + `test_freeze_gate_integrity.py` 31 + `test_production_authority_assembly.py` 3），45.33 秒。

**对抗抽检实证（SELF-TESTED 收尾后补充，临时篡改已字节级还原）**：向 `wiring.py` 追加一行探针（摘要 `f69c1cbc…`→`0c58b74f…`）后，门禁 `changed_external_paths` 立即标记该文件漂移，`test_production_composition_root_is_pinned_and_drift_forces_assembly_tests` **立即失败**（0.05 秒）；从字节级备份还原后摘要精确回到 `f69c1cbc…`、漂移标记消失、该测试重新通过，src/tests 聚合（`075b9570…`）全程未受影响，终态与第 6 节正式门禁测试快照逐字一致，无需重跑门禁。该实验证明基线保护是真实约束而非登记摆设。

## 6. 正式冻结门禁摘要与映射结果

`python scripts/freeze_gate.py`（仓库根，单次，2026-10-23T10:19Z）：

- **PASSED**，pytest 退出 0，未超时；门禁完整墙钟 **155.653 秒** < 300 秒（预算未动）。
- **collected node IDs 244 = passed 244**，0 failed / errors / skipped / deselected（JSON 报告的 `collected_test_node_ids` 计数与 passed 相互印证；`pytest_counts["collected"]` 在 -q 输出下无该行，以 node ID 清单为准，与 INT-1 同机制）。
- 选择集 17 个测试文件：本轮 3 个测试文件全部入册（新测试文件按 `resolve_tests` 对 tests/ 路径自动纳入，改动测试文件同理）；其余为 INT-1 阶段 delta（baseline=09860f8c）的既有映射与 agentos_v2/freeze_gate/CLI 三项外部漂移的强制映射。
- `uncovered_source_paths`、`missing_test_paths`、`missing_external_source_paths` 全空；wiring.py 摘要与基线一致（`f69c1cbc…`），freeze_gate.py 自身摘要 `bd589d79…`（改动后仍按既有机制强制映射 integrity 测试）。
- 历史已知耗时和 229.82 秒用于预算预检通过；未删测试、未调 timeout、未扩大跳过、未运行全量 pytest。
- 原始报告：`tmp/freeze_gate/20261023T101919Z.json` / `.log`。

## 7. 测试前后源码 SHA-256

| 项 | 测试前 | 测试后 |
| --- | --- | --- |
| AgentOS src/tests 聚合（452 文件） | `075b9570cc4fd944232d0109ca6f93cd7e6c722701ff1315f900aeb78c3ed3e0` | 同左（逐字一致） |
| `apps/agent/app/execution/wiring.py` | `f69c1cbc280a484c349eca24a7c0fbf34dad10ac2eacf3af32a66fb285e46be3` | 同左 |
| `scripts/freeze_gate.py` | `bd589d79c1800cf8f393db5765d7cd0f4121acfeb5f768d88884865757a9a8d7` | 同左 |
| `apps/agent/app/api/agentos_v2.py` | `2127e6e7…dabe14e3`（未改动，与 INT-1 相比的本机行尾漂移属既有状态） | 同左 |
| `scripts/upgrade_agentos_c2_schema.py` | `72b55f01…c3cb08cd`（未改动） | 同左 |

## 8. `git diff --check HEAD` 结果

退出码 0。输出仅 5 条行尾转换 warning（LF→CRLF 提示，含 2 个前端并行文件），无 whitespace 错误。

## 9. 最终 Git 状态与未完成限制

- 本轮改动：`apps/agent/app/execution/wiring.py`、`apps/agentOS/tests/storage/test_c2_schema_upgrade.py`、`apps/agentOS/tests/storage/test_freeze_gate_integrity.py`、`scripts/freeze_gate.py`（M）；`apps/agentOS/tests/components/planner/test_production_authority_assembly.py`（新增）；本记录（新增）。全部未暂存、未提交、未推送。
- 并行工作完整保留：任务书 5 项 + 入场时新发现的 4 个前端 M 与 3 个前端未跟踪文件 + INT-2A-0 报告。
- 禁令自查：未连接/修改真实业务数据库；未执行 `--apply`（升级仅发生在临时测试库，等价入口 `ops.upgrade_databases`）；未改 compose/生产配置；未启用真实生产执行链；未新增 HTTP 入口；未开发前端；未接 ACP/OpenClaw/ZCode/DeepSeek Harness 等外部执行后端；未改 ADR；未 Push/Merge/部署/Commit。
- 保留边界：接受 Initial Commit 后 Run 停在规划等待属既定阶段边界（生命周期驱动是后续阶段的职责），本轮未以任何 legacy 直执行捷径制造测试成功；三库升级前置条件（备份/维护窗口/正式预检）仍处 INT-2A-0 报告的 BLOCKED 状态；跨库非联合原子性限制继续保留。
