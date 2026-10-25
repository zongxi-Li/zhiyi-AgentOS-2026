# C2B-INTEGRATION-INT-2A-0-阶段合并记录

> 本文按阶段合并开发记录。来源文档内容原样保留，原文件继续留在本目录。

## 原始记录目录

- `C2B-INTEGRATION-INT-2A-0-生产装配入场审计与接线设计.md`

---

<!-- 原始记录：C2B-INTEGRATION-INT-2A-0-生产装配入场审计与接线设计.md -->

# INT-2A-0：生产装配入场审计与接线设计

日期：2026-10-23。阶段状态：**AUDITED（只读审计完成，未改任何生产源码，未提交，未部署）**。本文档为 INT-2A-0 交付物，供架构审查；审查通过前不进入 INT-2A-1。

## 结论

1. 入场基线声明与实际 Git 状态**全部吻合**：HEAD、冻结提交父链、冻结提交文件范围、451 文件聚合源码摘要、门禁脚本与 manifest 摘要均逐项复算对上；五个并行修改文件原样保留。
2. 生产装配链现状：五类 Authority（Planning Commit / Graph Materialization / Graph Activation / Graph Handoff / Execution Permit）**代码已实现、测试夹具可调用，但生产零装配**——生产 Composition Root（`apps/agent/app/execution/wiring.py`）没有任何 `enable_*` 调用，HTTP 零入口，真实部署零验证。当前生产是 legacy ACG 直执行路径。
3. 三库实况（2026-10-23 只读探测）：workflow 与 checkpoint 库**未装 C2 表**（UPGRADE_REQUIRED），identity 库 user_version=3（符合合同）；但**升级前置条件 BLOCKED**——checkpoint 库无任何备份，workflow 库备份停在 2026-09-14，无维护窗口批准证据，正式只读预检未在维护窗口执行。
4. 未发现 P0。P1×3、P2×4 见第四节。
5. INT-2A-1 最小接线方案见第五节：改 1 个生产文件（wiring.py，flag 门控、默认关）、扩 1 个门禁测试、新增 1 个装配级测试文件；五权威按既有不变式顺序装配；硬约束为「C2 开则语义收敛必须同时开，否则启动 fail-closed」。

---

## 一、入场基线核验记录

| 核验项 | 声明 | 实测 | 结论 |
| --- | --- | --- | --- |
| HEAD | `da11315470169b5e971170a83c7ef20b1128f75d` | `git rev-parse HEAD` 一致；分支 `master` | ✓ |
| 冻结提交 | `fix(c2b-int1): 完成 Permit 反向关联修复与最终冻结` | `da113154`，主题一致 | ✓ |
| 冻结提交父 | — | `11e6426899aad683f6f88091a13f38abef2ffa`（`11e64268 feat(acg-graph)`），与 INT-1 实施记录第 147 行声明一致 | ✓ |
| 冻结提交范围 | — | 恰 3 文件：INT-1 实施记录.md（+155）、`src/support/stores/c2_schema_upgrade.py`（+16）、`tests/storage/test_c2_schema_integrity.py`（+38/-4），与记录第 149 行"原子提交范围"一致 | ✓ |
| INT-1 源码摘要 | `5ffb32c3…4a581` | 用门禁自身 `freeze_gate.source_snapshot()`（`scripts/freeze_gate.py:174-183`）在工作区重算 = `5ffb32c30c9835dcb5bf9e6166b1539c7dc44d4258a65d07d6ea4f5022e4a581`，451 个 `.py` | ✓ |
| 门禁脚本摘要 | — | `scripts/freeze_gate.py` SHA-256 = `4405b0b9…7015e`，与 INT-1 记录第 52/99 行一致 | ✓ |
| INT-1 manifest | — | `scripts/freeze_gate_baselines/c2b-int1-entry.json` SHA-256 = `54ccc02a…1a591`，与记录第 99 行一致 | ✓ |
| 远端关系 | — | master 领先 `origin/master` 恰 1 笔（即冻结提交本身未推送）；origin=Gitee，mirror=GitHub | ✓ |

摘要算法备注：INT-1 摘要按**工作区原始字节**定义（含 checkout 行尾）。按库内 blob（全 LF）重算得 `6fccd917…`，不匹配属预期；门禁合同以工作区字节为准，且 `apps/agentOS` 工作区当前无改动，故工作区摘要=冻结时摘要。

并行工作保护（未覆盖、未暂存、未提交、未清理）：

- `apps/frontend/src/components/agentos/AcgTopologyGraph.spec.ts`（M）
- `apps/frontend/src/components/agentos/AcgTopologyGraph.vue`（M）
- `apps/frontend/src/utils/acgExecutionLayout.spec.ts`（M）
- `apps/frontend/src/utils/acgExecutionLayout.ts`（M）
- `docs/架构设计/架构图/知弈AgentOS_ACG总体架构 - 副本.drawio`（未跟踪）

暂存区为空；本轮全程只读，未重置、未 stash、未改任何文件。

## 二、生产调用链审计

### 2.1 真实调用链（生产 = ai-service 容器）

```text
docker compose ai-service（compose.yaml:83-161，ENVIRONMENT=production）
  → uvicorn → apps/agent/app/main.py:44  runtime = build_default_runtime()   # 模块导入期构造
  → main.py:47  coordinator = RunExecutionCoordinator(runtime)
  → main.py:114-118  agentos_v2.create_router(runtime, coordinator) 挂载 /ai
  → lifespan（main.py:50-78）：tool warmup → model_setup.start()
      → bind_registered_planner_llm（main.py:62）→ coordinator.startup()（main.py:64）
Composition Root：apps/agent/app/execution/wiring.py:316-498 build_default_runtime
Runtime facade：apps/agentOS/src/runtime/workflow_runtime.py ExecutionRuntime
API → 调度：apps/agent/app/execution/coordinator.py submit/_run_managed
  → ExecutionRuntime.execute_prepared_run（workflow_runtime.py:992）
  → _execute_acg（:1099）→ _claim_acg_execution（:1134，Run fence + 激活头 + Permit 校验）
  → ACGExecutionService.execute（runtime/acg_execution.py:153）
      节点派发包装器 _ready_node_runner（acg_execution.py:541）
NodeRunner：components/executor/node_runner.py（invocation_guard 回调 :425-426）
Authority：runtime/{planning_commit,graph_materialization,graph_activation,graph_handoff,execution_permit}.py
```

两个 `build_default_runtime` 并存：生产真身是 `apps/agent/app/execution/wiring.py:316`；`apps/agentOS/src/runtime/workflow_runtime.py:2637` 的同名函数仅被 `runtime/__init__.py:22-27` 懒重导出与 `runtime/legacy/__init__.py` 兼容层引用，**无生产调用者**。

### 2.2 五类 Authority 接线矩阵

| Authority | 挂载方法（workflow_runtime.py） | 代码已实现 | 生产已接线 | 测试夹具可调用 | 真实部署已验证 |
| --- | --- | --- | --- | --- | --- |
| Planning Commit | `enable_planning_commit(store)` :1191 | ✓ `runtime/planning_commit.py:349` | ✗ | ✓ 12 个测试文件（tests/components/planner/test_planning_commit_runtime.py 等） | ✗ |
| Graph Materialization | `enable_graph_materialization(store)` :1196 | ✓ `runtime/graph_materialization.py:20` | ✗ | ✓ test_initial_graph_materialization.py 等 | ✗ |
| Graph Activation | `enable_graph_activation(store)` :1201 | ✓ `runtime/graph_activation.py:51` | ✗ | ✓ test_graph_activation*.py 等 | ✗ |
| Graph Handoff | `enable_graph_handoff(store, staged)` :1206 | ✓ `runtime/graph_handoff.py:42` | ✗ | ✓ test_graph_handoff.py 等 | ✗ |
| Execution Permit | `enable_execution_permit(store)` :1218 | ✓ `runtime/execution_permit.py:58` | ✗ | ✓ test_execution_permit.py / test_initial_execution_permit.py | ✗ |

"生产零接线"的直接证据：

- `grep enable_*|authority 门面` 于 `apps/agent/`、`apps/local-runtime/` 全部零命中；门面（`issue_execution_permit` :1223、`materialize_initial_commit` :1266 等）非测试引用仅 `src/examples/contract_review.py`。
- `apps/agentOS/tests/storage/test_c2_schema_upgrade.py:330-360` 门禁测试**锁死**该合同：`build_default_runtime(environment=…, AGENTOS_MISSION_SEMANTIC_CONVERGENCE=false)` 后五个 authority 属性必须为 `None`，且 workflow/checkpoint 库不得出现任何 C2 表（隐式升级被断言为失败）。
- HTTP 面零入口：`apps/agent/app/api/agentos_v2.py` 全部 POST 端点清单中无 activation/permit/handoff/materialization 任何端点。

### 2.3 关键语义与证据

**构造不变式（enable 顺序由构造函数强校验，乱序即抛错）**：

1. PlanningCommit：store 必须与 workflow 主库同文件（`runtime/planning_commit.py:350-351`）。
2. Materialization：要求 planning store + workflow 同库（`graph_materialization.py:21-24`）。
3. Activation：要求 materialization + planning + workflow 三者同库（`graph_activation.py:52-58`）。
4. Handoff：store=workflow 主库；staged store 必须等于 checkpoint 库且**不得**与 workflow 同库（`graph_handoff.py:46-47`）。
5. Permit：要求 handoff authority 已挂、三库路径两两满足等式（`execution_permit.py:58-64`）。

五个 C2 Store 全部 **verify-only**（`mode=rw` 连接、构造即校验 marker 表、绝不执行 DDL，升级走各自静态 `upgrade_schema`；如 `execution_permit_store.py:19-23,46-49`）。表全部建在 workflow 主库（唯一例外：`staged_graph_checkpoints` 在 checkpoint 库，`graph_handoff_store.py:18-20`）。

**功能开关**：

- `AGENTOS_MISSION_SEMANTIC_CONVERGENCE`：默认 `false`（`wiring.py:394`）；compose.yaml 与全部 .env 均**未设置** → 生产=关。开启时 `enable_existing_mission_semantics()` 仅校验已装的 S00-01 表、绝不建表（`sqlite_workflow_store.py:60-72`），并挂语义服务+委托校验（`wiring.py:399-416`）；此后 `prepare_run` 强制要求可信语义 principal（`workflow_runtime.py:628-633`），POST /missions 拒绝无 semantics 的创建（`agentos_v2.py:2297-2298`）。
- `AGENTOS_ALLOW_LEGACY_MISSION_INTENT`：默认 `false`（`wiring.py:424`），生产未设置。
- **硬依赖（本轮新证实）**：C2 链硬依赖语义层——`planning_commit.py:89-90`（Initial 接受要求 principal 与服务一致）、`:134` 与 `execution_permit.py:378,458`、`graph_handoff.py:69`、`graph_materialization.py:70-104` 均直接读 `mission_semantic_state` 表 / principal。因此 C2 装配开启的前提是语义收敛同时开启且 S00-01 表已存在。

**Mission 创建后的自动执行路径（现状生产行为）**：POST /missions（`agentos_v2.py:2287-2378`）→ `runtime.create_mission`（:2323，`defer_identity_projection=True`）→ `runtime.prepare_run(…, defer_acg_planning=True)`（:2341）→ `coordinator.submit(run_id)`（:2351）→ 后台 worker（`coordinator.py:137`）→ `execute_prepared_run` → PLANNING → `_materialize_deferred_acg_run` → `_materialize_acg_run` 走 legacy L1-L3 规划/编译（`workflow_runtime.py:868-963`）→ `_execute_acg` 直执行。POST /missions/{id}/runs（:2736）同构。**该路径不经过任何 Authority。**

**ACTIVATED_PAUSED 处理**：定义于 `contracts/graph_activation.py:26,52`；激活提交后投影固定 `executionPermit: null`（:59-77）。执行侧 `_claim_acg_execution`：激活头存在而 permit authority 缺失 → `raise "activated but paused; no execution permit authority is attached"`（`workflow_runtime.py:1160-1162`）；authority 存在则 `assert_dispatchable` + `assert_settled_operations`（:1163-1167）。调度层在 4 个时点反复校验：派发入口（`acg_execution.py:589`）、资源分配后（:669）、节点 dispatch 前（:771）、每次模型调用 guard（:545-553 → `node_runner.py:425-426`）。**所有 permit 检查均以 `"graphActivation" in run.execution_state` 为前提**——无激活投影的 Run 走 legacy 直执行，这是设计上的向后兼容而非遗漏。

**Permit 状态机与幂等**：`PREPARING/ISSUED/REVOKED`（`contracts/execution_permit.py:41`），仅 ISSUED 可执行。`issue()` 以幂等键先查后写（`execution_permit.py:75-87`）+ 三列唯一索引（`execution_permit_store.py:12-14`）+ 事务内 CAS `UPDATE … WHERE status='PREPARING' AND checksum=?`（store:96-110）。同键重放=`IDEMPOTENT_REPLAY`，同 handoff 换键=`REJECTED`（测试证据 `test_initial_execution_permit.py:98-100`）。其余四类账本同样有 `idempotency_key UNIQUE` / 每源唯一索引（见各 store DDL）。

**三库 saga（非联合原子）**：Permit 签发跨 workflow（账本+Run 投影）、checkpoint（`save_promoted`）、identity（投影）三库各自独立提交，靠 `_checkpoint_is_promoted`/`_identity_matches_candidate` 重入对账（`execution_permit.py:174-230`）。Handoff 同为 saga 三步（`graph_handoff.py:392-440`）。

**fail-closed 清单（既有，无需新增）**：

- 生产缺 `AGENTOS_RESOURCE_CREDENTIAL_KEY` → 构造抛错（`wiring.py:328-331`）；缺 `AGENTOS_WORKFLOW_DB_PATH` → 抛错（:190-194）；单实例文件锁（:333）。
- C2 Store 构造时表缺失 → 抛错（verify-only，连空库都打不开）。
- Authority 缺失时五个门面全部返回 `AUTHORITY_DENIED` 拒绝（`workflow_runtime.py:1223-1282`），不抛异常、不降级执行。
- `planningCommitRequired` 的 Run 在无 planning authority 时拒绝执行（`workflow_runtime.py:997-998`、`:1113-1114`）。
- 激活 Run 无 permit authority → 执行认领即抛错（:1160-1162）。
- ACG+`require_planner_identity`（生产 wiring.py:439 恒 True）缺 identity 适配器 → 抛错（:671-674）。

**启动恢复真实行为**：构造期 Identity 对账（`wiring.py:443-446`）；`coordinator.startup()`（`coordinator.py:63-85`）→ `close_orphaned_runs`（→ `_recover_pending_planning_transitions` `workflow_runtime.py:2082-2085,2127` + `runtime_recovery_coordinator`，后者感知 `executionPermitId`，`runtime_recovery.py:385`）→ identity outbox 补投（失败不拉倒启动）→ 仅 `planningLoop.restartPending` 的 Run 重交执行 → 等待监视器。permit 已投影的 Run 在执行入口先 `reconcile_execution_checkpoint`（`workflow_runtime.py:1003-1005` → `permit_recovery.reconcile_checkpoint`，锁+fence 下只认已结算证据）。进程互斥另有 OS 级 Run fence（`support/run_execution_fence.py:34-63`，msvcrt/fcntl 非阻塞排他锁）。

## 三、三库升级前置条件核验表

预期合同（源自 `c2_schema_upgrade.py:30-41,95,154-157` 与 `storage/v2/sqlite.py:15`）：

| 库 | 生产路径（compose.yaml:98,99,106） | 预期 PRAGMA user_version | 预期表 |
| --- | --- | --- | --- |
| Workflow | /app/data/agentos/workflows.sqlite3 | 0 | planning_commit / graph_materialization / graph_activation / graph_execution_permit 四组 marker 表（版本均=1）+ graph_handoffs，及各自业务表与唯一索引 |
| Checkpoint | /app/data/agentos/langgraph_checkpoints.sqlite3 | 0 | staged_graph_checkpoints（DDL 逐字比对，无版本表） |
| Identity | /app/data/agentos/identity_v2.sqlite3 | 3（CURRENT_SCHEMA_VERSION） | 既有 V2 表，不动 |

检查方法：`python scripts/upgrade_agentos_c2_schema.py --workflow-db … --checkpoint-db … --identity-db …`（默认只读 INSPECT，READY/NOT_READY，退出码 0/2/1；`--apply` 才写且写前全文件预检，`c2_schema_upgrade.py:323-351`）。

实测（2026-10-23，对运行中容器 `kinlin-win-p1-001-ai-service-1` 以 `mode=ro` URI 只读探测；**非**维护窗口正式预检）：

| 项 | Workflow | Checkpoint | Identity |
| --- | --- | --- | --- |
| user_version | 0 ✓ | 0 ✓ | 3 ✓ |
| C2 表 | **0/8 缺失**（仅有 mission_semantic_* 5 表=S00-01 已装） | 仅 acg_execution_checkpoints，**staged_graph_checkpoints 缺失** | 合同不要求新表 |
| 判定 | UPGRADE_REQUIRED | UPGRADE_REQUIRED | READY |

| 前置条件 | 状态 | 证据 |
| --- | --- | --- |
| 1. 预期 Schema 版本及检查方法 | 已确认 | 上表 + 升级 CLI 源码 |
| 2. 业务库实际版本已证实 | **已证实（本轮只读探测）** | workflow/checkpoint 未装 C2 表；identity=3。注意：正式 `inspect_databases` 全量预检（含 Permit 反向关联证据校验）**未执行** |
| 3. 备份存在/时间/恢复验证 | **workflow：过时（最新 2026-09-14 `.before-owner-sync` 系列，落后现库 5 周+，现库 1.5GB）；checkpoint：无任何备份；identity：过时（9-10/9-14）。恢复演练证据：无** | 容器内 `ls /app/data/agentos/` |
| 4. 维护窗口批准 | **UNVERIFIED**（无任何批准记录） | — |
| 5. 只读预检已在目标库执行且 READY | **未执行**（本轮仅轻量版本探测；INT-1 合同要求停止写入后在维护窗口跑全量 inspect） | — |

**总结论：升级前置条件 = BLOCKED**（备份缺失/过时 + 无维护窗口 + 无正式预检）。本轮未连接修改真实库、未执行 `--apply`、未迁移、未部署、未启用生产执行、未签发任何执行许可。另登记一个事实：workflow 库内 mission_semantic_* 表的安装来源无法从当前证据追溯（`enable_existing_mission_semantics` 是 verify-only，说明历史上发生过一次显式安装动作），不影响 C2 判定。

## 四、P0/P1/P2 问题清单

**P0：无。**（审计阶段未发现必须先于一切修复的缺陷；生产现状=legacy 直执行属「未启用」而非「绕过」，与 C2B-ARCH V1 审计结论一致。）

P1-1 Checkpoint 库无任何备份。`--apply` 会写该库（staged 表 DDL），当前状态出错即无法回滚。升级前必须先补该库备份。

P1-2 Workflow 库备份严重过时（最新 2026-09-14，现库已增长至 1.5GB、持续有写入至 10-23）。INT-1 合同要求升级在停写维护窗口执行且拒绝时三库内容不变，但没有近备份则窗口内发现数据问题时无退路。

P1-3 冻结门禁外部基线不含 `apps/agent/app/execution/wiring.py`（`scripts/freeze_gate.py:127-133` 仅 agentos_v2.py / freeze_gate.py / 升级 CLI）。**生产 Composition Root 的改动对门禁不可见**。INT-2A-1 恰恰要改此文件，必须同步把 wiring.py 纳入 EXTERNAL_BASELINE 与 SOURCE_TEST_RULES 映射，否则装配改动逃逸门禁。

P2-1 `AGENTOS_MISSION_SEMANTIC_CONVERGENCE` 与 C2 装配的开关组合关系尚未成文：C2 链硬依赖语义层（第二节 2.3），但两个开关在部署配置里互相独立。INT-2A-1 必须实现「C2 开而语义关 → 启动 fail-closed」并以测试锁定。

P2-2 装配开启后 Mission 行为全局变化：`prepare_run` 因 planning authority 在场强制 `defer+planningCommitRequired`（`workflow_runtime.py:626-627,783-786`），Initial Commit 接受后 Run 停在 planningDeferred（:1031-1032「accepted planning fact; no graph has been materialized」），**自动执行消失**，直到 INT-4 生命周期驱动落地。这是设计语义但必须写进运维变更说明并由测试锁定。

P2-3 重启恢复与 ACTIVATED_PAUSED / PREPARING Permit 的交互在**装配级**（build_default_runtime 全链）无定向测试：既有覆盖在权威单元级（test_permit_recovery / test_initial_execution_permit 的进程切口用例）。INT-2A-1 应补装配级重启恢复用例。

P2-4 identity 库备份同样停在 9-10/9-14。本轮升级不写该库（user_version 已 3），风险低，但维护窗口备份策略应三库同覆盖。

（P3 略：agentOS 侧 `build_default_runtime` 与生产同名易混淆，建议文档标注即可，不改码。）

## 五、INT-2A-1 精确实施计划与验收条件

### 5.1 文件清单

**修改（3 个）**：

1. `apps/agent/app/execution/wiring.py` — 唯一生产改动。新增单一环境开关（建议名 `AGENTOS_C2_EXECUTION_AUTHORITIES`，默认 `"false"`；最终命名由架构审查定）。开启时：
   - 前置校验：`AGENTOS_MISSION_SEMANTIC_CONVERGENCE` 必须同时为 true，否则 `raise RuntimeError`（fail-closed，P2-1）。
   - 在 `ExecutionRuntime(...)` 构造完成（wiring.py:440）之后、`register_native_runtime`（:491）之前，按不变式顺序装配：
     ```python
     enable_planning_commit(SQLitePlanningCommitStore(workflow_path))
     enable_graph_materialization(SQLiteGraphMaterializationStore(workflow_path))
     enable_graph_activation(SQLiteGraphActivationStore(workflow_path))
     enable_graph_handoff(SQLiteGraphHandoffStore(workflow_path),
                         SQLiteStagedGraphCheckpointStore(checkpoint_path))
     enable_execution_permit(SQLiteExecutionPermitStore(workflow_path))
     ```
     （顺序与路径等式即 2.3 节构造不变式；`workflow_path` 复用 :332 的值，`checkpoint_path` 复用 :425 `AGENTOS_LANGGRAPH_CHECKPOINT_DB` 的值。参考实现=`src/examples/contract_review.py:266-274 attach_authorities`。）
   - 任何 Store 构造抛错（schema 未升级）**不得捕获降级**，直接中止启动。
   - `close_runtime`（wiring.py:501-532）的关闭清单追加五个 store + staged store（去重逻辑已有）。
2. `apps/agentOS/tests/storage/test_c2_schema_upgrade.py` — 扩展既有应用构造门禁测试（:330 起）：(a) flag=false 维持现状断言（已有）；(b) flag=true + 三库已 `upgrade_schema` → 五 authority 全部挂载且类型正确、close_runtime 可重复安全调用；(c) flag=true + C2 表缺失 → `build_default_runtime` 抛错且不写任何 C2 表；(d) flag=true + 语义收敛=false → 抛错。
3. `scripts/freeze_gate.py` — EXTERNAL_BASELINE 增补 `apps/agent/app/execution/wiring.py` 条目（以 INT-2A-1 定稿时摘要登记），SOURCE_TEST_RULES 增加该路径 → 上述测试的映射（P1-3）。

**新增（1 个）**：`apps/agentOS/tests/components/planner/test_production_authority_assembly.py`（命名可调）— 装配级闭环与恢复测试，全部经 `build_default_runtime(environment=…)` 驱动（该导入方式已被 test_c2_schema_upgrade.py:334 证明可行）：

- 用例 A（Initial 全链闭环）：临时三库 → 显式 `upgrade_schema`（复用各 store 静态方法，等价 CLI --apply 在测试库的效果）→ 构造（flag 全开）→ 语义创建 Mission → `prepare_run` → `execute_prepared_run`（Initial Commit 接受，Run 停 planningDeferred，断言不执行任何节点）→ `materialize_initial_commit` → `prepare_graph_activation` → `commit_graph_activation`（断言 ACTIVATED_PAUSED 且 `execute_prepared_run` 被拒：`_claim_acg_execution` 抛错）→ `prepare_graph_handoff` → `issue_execution_permit`（ISSUED）→ `execute_prepared_run`（首节点执行且仅一次；重复调用幂等）。
- 用例 B（装配级重启恢复）：沿 A 的库目录重新 `build_default_runtime` 构造第二实例 → 断言 ACTIVATED_PAUSED Run 不被 `coordinator.startup()` 等价逻辑自动执行；同幂等键重发 `issue_execution_permit` → `IDEMPOTENT_REPLAY`；PREPARING 中断态（借测试切口模拟）重放收敛。
- 用例 C（旧路径共存）：同一装配下，无 graphActivation 投影的历史 Run 仍走 legacy 直执行（向后兼容不被装配破坏）。

**明确不改**：五类 Authority/Store/contracts、`c2_schema_upgrade.py`、升级 CLI、`workflow_runtime.py`（enable_* 门面已够用，构造参数 `planning_commit_store` 不使用）、`agentos_v2.py`（HTTP=INT-3）、`coordinator.py`、`main.py`、compose.yaml（生产翻转开关属 INT-4 后的部署决策）、前端（INT-5）、scheduler/node_runner。不新增任何平行 Authority、Store、账本或状态机。

### 5.2 设计问题回答（对应任务书第四节）

- **构造顺序/依赖/生命周期**：见上；单实例、进程启动构造、`close_runtime` 统一关闭；不提供热插拔。
- **旧执行入口**：全部保留不动（legacy 直执行、checkpoint 恢复、审核恢复、单步重试）。需要"关闭"的是未来新 Mission 的自动直执行——由 INT-4 生命周期阶段显式迁移，本阶段仅以 flag 默认关保证生产行为零变化。
- **fail-closed**：schema 不匹配→Store 构造抛错→进程拒启；授权失效（permit REVOKED/投影漂移）→ `assert_dispatchable`/`_assert_dispatch_authority` 拒绝（`execution_permit.py:414-509`）；authority 中途摘除→997/1113/1161 三处既有门禁兜底。
- **防重复**：完全依赖既有唯一索引+幂等键+replay/conflict 语义+CAS（2.3 节），测试只验证不新增机制。
- **Coordinator/审批/恢复衔接**：coordinator 语义不变（只认 pending/retrying；permit Run 经 `execute_prepared_run:1003-1005` 先对账）；ReviewService 不变；重启恢复沿 `close_orphaned_runs`+`reconcile_checkpoint`，装配级覆盖由用例 B 补齐。
- **INT-2A-1 定向测试与独立验收标准**：
  1. 上述 (b)(c)(d) 与用例 A/B/C 全绿；不跑全量 pytest。
  2. `python scripts/freeze_gate.py` PASSED、预算内（300s 硬上限不放宽）、新增路径纳入映射后"未覆盖源码/缺失测试"为空。
  3. 前后 src/tests 聚合摘要与外部源码摘要记录在案；五个并行文件摘要不变。
  4. 边界：不接 HTTP、不动前端、不接外部执行后端、不连真实业务库、不部署、不推送；提交与否按届时任务书。

### 5.3 本阶段已遵守的禁令自查

未修改生产源码（本文档为唯一新增文件，属交付物）；未提交/推送/部署；未运行全量 pytest（本轮零测试执行，全部结论来自源码阅读+一次只读数据库探测）；未连接修改真实库、未 `--apply`、未迁移、未启用生产执行、未签发许可。

## 附：证据补遗

- 生产 Redis 协调：compose.yaml:156 `AGENTOS_COORDINATION_REDIS_URL=redis://redis:6379/1` → `RedisLeaseCoordinator` 活跃（wiring.py:346-352）。
- 冻结门禁机制备注：EXTERNAL_BASELINE 摘要不匹配时按 SOURCE_TEST_RULES 强制映射测试运行（freeze_gate.py:138-141,322-324），故 INT-1 后脚本自身摘要漂移（06816f40→4405b0b9）属受控状态。
- 容器实况：五容器 21h healthy（backend/frontend/ai-service/postgres/redis）；workflows.sqlite3 最后写入 10-23 08:47（服务在用）。
