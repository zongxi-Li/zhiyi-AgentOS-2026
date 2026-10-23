# INT-1：Permit—Run 反向关联修复

日期：2026-10-23。修复阶段状态：**SELF-TESTED**。独立源码审查及最终冻结依据见末节；冻结不作为生产部署 ACCEPT。

## 入场

HEAD / master：`11e6426899aad683f6f88091a13f38abebdf2ffa`。入场 `git status --short` 及暂存区均为空。此前 FIX2 已在 `92945706` 提交，前端工作另在 `11e64268` 提交；本轮保留这些提交，不回退历史工作。

入场 AgentOS src/tests 共 451 个 Python 文件，聚合 SHA-256：

```text
49a91f777b2d5cc520b0374ddedc26f5b385e3d8ad8bbbdc7db3816a319c913a
```

实际读取当前 `_inspect_evidence()`、Permit Store 的 `_decode()` 和 Activation Store 的 `validate_activation_run()` / `_issued_permit()` 后确认：后两者可校验完整 Run→Head→Activation→Materialization→Permit→Handoff 身份，但只有被遍历到的非空 Run Permit 投影才会进入这条校验链。

## 修复前反例

复用 `tests/storage/test_c2_schema_integrity.py::two_permits`：同一 Workflow SQLite 中两个不同 Mission/Run，均通过正式 Initial Commit、Materialization、Activation、Handoff 与 ISSUED Permit 链建立。没有预填成功收据或 Mock 成功 CAS。

仅通过 SQL 损坏其中一个 Run 的 payload，分别删除 `executionPermit`、将其置为 null、删除整个 `graphActivation`；其余正式记录保留。三种情况的 `inspect_databases()` 均错误返回 `READY`。把另一个 Run 也指向该 Permit 的重复关联则已被既有正向校验拒绝。

修复前执行：

```text
cd apps/agentOS
python -m pytest -q tests/storage/test_c2_schema_integrity.py::test_issued_permit_requires_exactly_one_owner_projection --tb=short
```

结果：3 failed / 1 passed，pytest 22.09 秒，含启动墙钟 26.549 秒，退出 1；src/tests 快照 `d062adf2cfcea465595f3c5a47e38fb57728d64e1e7e932df7ccd887d434615a`，运行前后相同。三项失败均为期望 `INVALID`、实际 `READY`。原始日志与元数据：`tmp/c1_audit/int1-reverse-before.log` / `.json`。

根因：遍历集合来自非空 Run 投影，投影消失会使仍然持久存在的 ISSUED Permit 从关联验证中消失；已有 Permit→Handoff 校验无法证明 Run 采用该许可。

## 最小补丁与测试范围

- `src/support/stores/c2_schema_upgrade.py::_inspect_evidence()`：在既有同一个 Workflow 只读事务内，记录通过 `validate_activation_run()` 的 Permit→Run 关联；逐条用现有 `SQLiteExecutionPermitStore._decode()` 校验 Permit 合同、索引及 checksum；每条 ISSUED Permit 必须恰好有一个已验证的所属 Run。缺失或错配返回带 Permit/Run 定位的 `INVALID`。
- 身份语义仍由已有 `validate_activation_run()` 负责，包括 Run/Mission、Graph ID/Version、Activation、Handoff、Permit、AttemptGeneration 和完整投影。没有复制另一套授权判断；新增检查只闭合反向覆盖。
- PREPARING 不要求签发后的 Run 投影，继续使用已有 Handoff/Saga 校验。合法 STAGING、中断安装恢复及合法执行后的 Checkpoint 推进保持原合同。
- `tests/storage/test_c2_schema_integrity.py`：新增四项缺失/空值/Activation 缺失/重复关联测试，并扩展重算 checksum 的篡改集，加入 Permit 指向其他 Run 的情况（同步改变索引字段，正式 typed reader 仍可读）。保留原 Mission/Graph 篡改、引用其他有效 Permit、合法双 Run 和真实 Native 完成节点的回归。
- 所有拒绝用例比较 Workflow、Checkpoint、Identity 三库的完整 `iterdump()`，涵盖 Schema、索引、触发器和记录。新增反向用例分别在 inspect 后及 upgrade 拒绝后检查 dump 相同；预检拒绝发生于任何升级写入前。

本轮没有修改 Schema、Authority、执行权限策略、默认装配、HTTP API、前端、冻结预算或原基线。

## 最终快照及证据

最终 src/tests 451 个 Python 文件，聚合 SHA-256：

```text
5ffb32c30c9835dcb5bf9e6166b1539c7dc44d4258a65d07d6ea4f5022e4a581
```

算法：对 src/tests 中每个 `.py` 的原始字节计算 SHA-256，按仓库相对路径排序，组成以换行分隔且无末尾换行的 `path digest` 清单，再计算 UTF-8 清单 SHA-256。外部门禁脚本未修改，SHA-256 仍为 `4405b0b923d828574712e867fa1c40b6a6e90103e362f23889986940b277015e`。

`python scripts/freeze_gate.py --dry-run`：退出 0，0.268 秒，16 个测试文件，未覆盖源码、缺失测试、缺失外部源码均为空，diff check 退出 0。原始 JSON：`tmp/int1-reverse-dry-run.json`。

测试环境：Windows、Python 3.14.5，默认计时精度；不请求 1ms，不运行全量 pytest。

最终源码定向回归：

```text
cd apps/agentOS
python -m pytest -q tests/storage/test_c2_schema_integrity.py tests/storage/test_c2_schema_upgrade.py --tb=short
```

61 passed，0 failed，1 项已有 Pydantic 弃用警告；pytest 144.57 秒，含启动墙钟 148.285 秒，退出 0。运行前后 src/tests 与外部源码摘要均一致。覆盖新增五项参数用例和既有正向关联、STAGING、Checkpoint 前进、安装恢复及拒绝测试。原始结果：`tmp/c1_audit/int1-reverse-targeted.log` / `.json`。

正式冻结门禁（只运行一次，仓库根目录）：

```text
python scripts/freeze_gate.py
```

- `PASSED`，退出 0；235 个收集 node ID，235 个唯一 node ID，235 passed，0 failed / errors / skipped / deselected，2 项既有弃用警告。
- pytest 118.56 秒；门禁完整墙钟 **126.782 秒**，外层启动器 126.995 秒。保持 300 秒硬上限，未删减安全用例、修改 timeout 或扩大跳过范围。
- 历史已知测试耗时累计 182.130 秒用于原有预算预检；未知项保留在原始报告。最终采用实际墙钟，不把历史估算当实际耗时。
- 16 个测试文件覆盖本轮五项新增参数用例、既有 Schema 版本/损坏/恢复拒绝、正向关联、STAGING、Checkpoint 前进、Permit、资源/Scheduler、C1 纵向及交付等既有映射。未覆盖源码、缺失测试、缺失外部源码均为空。
- 运行前后 src/tests 聚合与外部源码摘要相同，最终快照即上文 `5ffb32c3…`；原 INT-1 manifest 未变化，SHA-256 仍为 `54ccc02a3d0ba550fffff8dd23f259460977ae0a75f3d8eea4d7c1848ce1a591`。
- 原始证据：`tmp/freeze_gate/20261022T163349Z.log` / `.json`，外层 stdout `tmp/int1-reverse-freeze-console.json`；逐文件最终快照 `tmp/int1-reverse-final-snapshot.json`。日志时间为 UTC，本地日期为 2026-10-23。
- `git diff --check` 退出 0。未运行全量 pytest，不将本次定向门禁等同全量无回归。

最终变更范围为本实施记录、`src/support/stores/c2_schema_upgrade.py`、`tests/storage/test_c2_schema_integrity.py`。HEAD 未改变，仍为 `11e6426899aad683f6f88091a13f38abebdf2ffa`，暂存区为空。运行期间出现用户并行改动 `apps/frontend/src/components/agentos/AcgTopologyGraph.spec.ts` / `AcgTopologyGraph.vue`，本轮未编辑、暂存、覆盖或清理，未将其算入 AgentOS 验证结论。

## 保留边界

本检查要求停止业务写入后在维护窗口执行。Workflow 关联读取位于同一读事务，但 Workflow、Checkpoint、Identity 及各升级步骤仍不具备联合原子性。本次没有解决并发升级时的跨库竞态，也没有新增跨库锁或事务。

证据完整性预检不等于当前执行授权、生产部署验收或对恶意数据库篡改的全面取证。不自动补建丢失事实，不通过降级 Permit 状态、回填投影或重新执行节点修复损坏。独立人工验收应复核上述反例、正式门禁和维护窗口条件，再决定是否冻结；本轮仅 SELF-TESTED，不自行宣布 ACCEPT。

全部修改保持未暂存、未提交、未推送；不升级真实业务数据库。

## FINAL-FREEZE：最终冻结复核（2026-10-23）

本节追加最终冻结依据。前述 SELF-TESTED、未提交状态及测试耗时是修复实施阶段的历史快照，不代表本轮入场状态。

### 入场清单与范围

- [x] 核对 HEAD / 分支：`11e6426899aad683f6f88091a13f38abebdf2ffa` / `master`，本地跟踪 `origin/master`；暂存区为空。
- [x] 完整阅读两个核心文件相对 HEAD 的差异及本实施记录。补丁与已审查内容一致，入场 src/tests 摘要为 `5ffb32c30c9835dcb5bf9e6166b1539c7dc44d4258a65d07d6ea4f5022e4a581`，451 个 Python 文件。
- [x] 核对固定 INT-1 基线、门禁映射和预算：原 manifest 原始字节 SHA-256 `54ccc02a3d0ba550fffff8dd23f259460977ae0a75f3d8eea4d7c1848ce1a591`，445 项内容聚合 `cb5809b8a2e29278d39d6ab70c6bd1567da7073148195201d013f1105f9a2c47`；`load_baseline()` 认证通过，预算保持 300 秒，门禁脚本 SHA-256 仍为 `4405b0b923d828574712e867fa1c40b6a6e90103e362f23889986940b277015e`。
- [x] 识别、排除并保留四个前端并行修改：`AcgTopologyGraph.vue`、`AcgTopologyGraph.spec.ts`、`acgExecutionLayout.ts`、`acgExecutionLayout.spec.ts`，以及未跟踪的 `docs/架构设计/架构图/知弈AgentOS_ACG总体架构 - 副本.drawio`。已记录入场原始内容摘要，不纳入 INT-1 提交。

正式修复范围仍仅为两个核心文件和本记录，没有新增或修改生产合同：

| 文件 / 位置 | 冻结内容 |
| --- | --- |
| `src/support/stores/c2_schema_upgrade.py:232` | 正向关联通过既有 `validate_activation_run()` 后登记所属 Run；同一 Workflow 读事务遍历全部 Permit，ISSUED 必须恰有一个身份一致的已验证 Run。 |
| `tests/storage/test_c2_schema_integrity.py:60` | 重算 checksum 后跨 Run/Mission/Graph 篡改、其他有效 Permit 引用及原有拒绝回归。 |
| `tests/storage/test_c2_schema_integrity.py:97` | 投影删除、null、Activation 投影缺失和重复关联反例；三库完整 SQL dump 在 inspect 与升级拒绝前后不变。 |
| 本实施记录 | 修复前失败证据、双向合同、修复自测历史和本轮最终冻结证据。 |

源码复核：Run 整行不存在时不会进入正向集合，仍存在的 ISSUED Permit 会因没有已验证 owner 被拒绝；这是当前反向遍历的直接分支推论，本轮未把它写成新增独立删除 Run 实验。PREPARING 不进入 ISSUED owner 要求，仍接受既有 Saga 依赖检查；STAGING 与正常 Checkpoint 推进由实际回归验证。没有发现新的 P0/P1，也没有为本轮冻结改动生产修复或测试断言。

### 审查来源与实际验证

本轮用户任务书明确告知：Permit—Run 补丁已经通过独立源码审查。这里仅登记审查确认补丁逻辑，**不声称审查方独立复跑了测试**。以下命令和结果由本轮冻结执行者实际运行，属于本地冻结验证；不把本地自测自行命名为新的独立 ACCEPT。

定向命令在 `apps/agentOS`：

```text
python -m pytest -q tests/storage/test_c2_schema_integrity.py tests/storage/test_c2_schema_upgrade.py --tb=short
```

结果：61 passed，0 failed，1 项既有弃用警告；pytest 93.18 秒，完整启动墙钟 **99.358 秒**，退出 0。包含新增反向关联反例及相关 INT-1 回归；没有重复单独跑这两份文件内的相同 node ID。测试前后 src/tests 与外部源码摘要相同。原始日志/元数据在 `tmp/c1_audit/int1-final-freeze-targeted.log` / `.json`。

最终正式门禁（仓库根目录，单次运行）：

```text
python scripts/freeze_gate.py
```

结果：`PASSED`，退出 0；收集 235 个唯一 node ID，235 passed，0 failed / errors / skipped / deselected，2 项既有弃用警告；pytest **197.75 秒**，门禁完整墙钟 **205.163 秒**（外层启动器 205.351 秒），小于 300 秒。

16 个测试文件的映射有效，未覆盖源码、缺失测试、缺失外部源码均为空。历史已知耗时总和 203.200 秒用于门禁原有的预算预检，不作为本次实际耗时。没有删除测试、调整 deadline、扩大跳过范围或运行全量 pytest。

测试前后及冻结前的 src/tests 快照均为：

```text
5ffb32c30c9835dcb5bf9e6166b1539c7dc44d4258a65d07d6ea4f5022e4a581
```

原基线认证通过且未修改；门禁脚本、外部 API 和升级 CLI 的内容摘要均与入场一致。核心修改与独立审查补丁一致，本轮只补记录，没有再修改生产代码或测试。

证据位置：`tmp/freeze_gate/20261023T083403Z.log` / `.json`，外层 stdout `tmp/int1-final-freeze-console.json`，入场逐文件 manifest 和并行文件摘要 `tmp/int1-final-freeze-entry.json`。临时日志遵循仓库 `tmp/` 忽略规范，不整包归档入 Git；本记录保留可复现命令、精确摘要、数量和耗时。

### 本地冻结提交

最终验证完成，允许作为受限 INT-1 基线冻结：**INT-1 FROZEN**。原子提交范围仅含 `c2_schema_upgrade.py`、`test_c2_schema_integrity.py` 和本记录。提交主题：`fix(c2b-int1): 完成 Permit 反向关联修复与最终冻结`。包含本节的该提交即为冻结身份，提交前父 HEAD 是 `11e6426899aad683f6f88091a13f38abebdf2ffa`；提交后的精确 SHA 由 Git 历史及本轮交付结果定位，避免在提交正文文件内自引用提交 SHA。

`git diff --check HEAD` 通过，暂存前 index 为空；精确暂存并审查 staged diff，不包含前端或 Draw.io 文件。预期提交后分支仍为 master，暂存区为空，四个前端修改及未跟踪 Draw.io 副本继续留在工作区；入场内容摘要用于确认没有覆盖这些并行工作。没有 Push、Merge、部署、真实业务库升级或正式 ADR 修改。

### 受限冻结边界

仅冻结 INT-1 的 Schema 显式升级及证据完整性修复。没有执行真实业务数据库升级、生产装配、HTTP 接线、部署或全量 pytest。跨库无联合原子事务、需要停止写入的维护窗口、多主机/跨进程在线迁移未经验证等边界继续保留。

INT-2 开始前须独立核对实际业务库路径、版本、备份、维护窗口及预检结果；随后另行审计默认 Composition Root 的 Authority 显式装配、fail-closed 行为和集成验证。INT-1 冻结不授权接入、激活或执行节点，更不等同生产发布验收。
