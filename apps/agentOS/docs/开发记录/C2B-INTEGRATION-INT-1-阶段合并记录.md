# C2B-INTEGRATION-INT-1-阶段合并记录

> 本文按阶段合并开发记录。来源文档内容原样保留，原文件继续留在本目录。

## 原始记录目录

- `C2B-INTEGRATION-INT-1-Schema显式升级实施记录.md`
- `C2B-INTEGRATION-INT-1-FIX实施记录.md`
- `C2B-INTEGRATION-INT-1-FIX2实施记录.md`
- `C2B-INTEGRATION-INT-1-Permit反向关联修复实施记录.md`

---

<!-- 原始记录：C2B-INTEGRATION-INT-1-Schema显式升级实施记录.md -->

# C2B-INTEGRATION-INT-1：C2 Schema 显式升级

状态：SELF-TESTED，等待独立验收。本任务不接线 Authority、不启用语义收敛、不修改默认执行路径。

## 入场及迁移差异审计

2026-10-22，HEAD `09860f8c88c4b8d40cac2c80ca836f0bfa5a2c35`，暂存区为空。入场仅两份未跟踪用户文档 `C2B-ARCH-V1全系统架构收敛审计.md`、`C2B-ARCH-V1模块接线与完成度矩阵.md`；保留原文，不纳入本轮改动。445 个 src/tests Python 文件原始字节聚合为 `cb5809b8a2e29278d39d6ab70c6bd1567da7073148195201d013f1105f9a2c47`。

以下从真实建表代码及其在临时 SQLite 中的输出核对，不代表已检查或升级任何业务数据库。没有统一全局 Schema 版本；现有机制为各 Store 的显式 `upgrade_schema`、Workflow 语义版本表及 Identity `PRAGMA user_version`。本轮只做运维编排，不另建迁移账本。

| 数据库/阶段 | 真实建表入口 | 表及版本 | 关键约束/索引 | 本轮差异 |
|---|---|---|---|---|
| Workflow 基础 | SQLiteWorkflowStore._init_schema | tasks、runs、task_copilot_permissions、run_planning_inputs、run_copilot_exchanges、lifecycle_outbox；user_version=0 | tasks/runs 主键；planning_inputs、exchanges 的 run+operation 唯一；permission CHECK；既有 Run 概览索引 | 现有库只验证，不运行会回填、重建索引的构造函数 |
| Workflow 语义前置 | SQLiteWorkflowStore._init_semantic_schema | mission_semantic_schema=[1]；state/commits/receipts/outbox、mission_revision_decisions | Mission revision/operation 唯一、revision CHECK、复合主键 | 现有库必须已具有兼容前置结构；不自动安装语义前置、不启用服务 |
| Planning Commit | SQLitePlanningCommitStore.upgrade_schema | planning_commit_schema=[1]、planning_commit_records、planning_commit_outbox | commit PK、key UNIQUE、mission+revision UNIQUE；planning_graph_source_unique 为 graph_revision 的 sourceCommitId 部分表达式唯一索引 | 缺失时调用原升级函数安装；已有内容保留 |
| Materialization | SQLiteGraphMaterializationStore.upgrade_schema | graph_materialization_schema=[1]、graph_materializations | materialization PK；graph_materialization_key_unique、graph_materialization_source_unique | 同上，完整定义校验 |
| Activation / Head | SQLiteGraphActivationStore.upgrade_schema | graph_activation_schema=[1]、graph_activations、graph_activation_heads | activation PK；graph_activation_key_unique、graph_activation_materialization_unique；Head run PK、activation UNIQUE | 同上，不创建 Head 行或版本 |
| Handoff | SQLiteGraphHandoffStore.upgrade_schema | graph_handoffs；无独立版本表，以严格 DDL 判别 | handoff PK；key、activation UNIQUE | 同上，不写 STAGING/STATE_PREPARED 事实 |
| Permit | SQLiteExecutionPermitStore.upgrade_schema | graph_execution_permit_schema=[1]、graph_execution_permits | permit PK；key、handoff、activation UNIQUE | 同上，不签发许可 |
| Checkpoint | ACGCheckpointStore 构造基础表；SQLiteStagedGraphCheckpointStore.upgrade_schema 增量 | acg_execution_checkpoints；staged_graph_checkpoints；user_version=0 | 正式 CP(thread_id,checkpoint_id) 复合 PK，version 列；staged checkpoint PK、handoff UNIQUE | 既有库要求当前正式基础表，仅安装 staged 表 |
| Identity | SQLiteV2Storage + storage/v2/schema.py | user_version=3，20 表、23 显式索引、8 触发器 | 六级身份链外键与 CHECK、唯一约束，Artifact/绑定不可变触发器 | 已具备能力，现有库只读验证；不运行旧版本 backfill，不重复建表 |

Workflow C2 增量共有 11 表（4 个版本标记表、7 个业务表）及 5 个显式唯一索引；无 SQL 外键、无触发器，不能把 Authority 内的跨表校验称作数据库 FK。Checkpoint 增量 1 表、1 个内联 UNIQUE。所有自动索引由原表的 PK/UNIQUE 产生，不另造或替换。Identity 8 个现有触发器为 attempts_require_same_mission、task_plan_node_requires_same_mission、task_binding_requires_same_mission、execution_binding_requires_realization、artifact_requires_complete_identity、artifact_immutable_update、run_artifact_binding_requires_consistency、run_artifact_binding_immutable_update；本轮全部保留并核对定义。

精确差异由检查模式对操作者显式指定的三个文件生成 missing/present 列表；不按文件名猜库角色、不扫描 data 目录、不读取默认环境数据库。已有同名错定义、未知版本、缺失前置表或版本已声明完成但正文表缺失，均拒绝修复。缺失的已定义 C2 索引只在历史数据满足唯一性时允许原升级函数补建；同名错误索引不 DROP、不替换。

## 最小方案与操作边界

仅复用原 Schema 定义/升级器；现有库在任何写操作前全部预检。新库必须由操作者额外显式声明初始化空库，才复用原基础初始化器和 Identity v3 初始化器；初始化不能处理含业务表的不兼容旧库。无跨文件联合事务；每个原升级器的 COMMIT 为自己的完成点，部分完成后根据版本/完整 DDL 再检查、按原顺序续跑。维护期间应停止业务进程并保留经 SQLite backup 的备份；预检不提供跨进程文件替换锁或跨库联合快照。

## 实际入口与兼容规则

新增 `src/support/stores/c2_schema_upgrade.py` 是运维函数库，不由 Runtime 或 Composition Root 导入。运维入口为仓库根目录 `scripts/upgrade_agentos_c2_schema.py`。所有数据库路径必填、绝对路径、三个文件互不相同；拒绝软链接、同文件硬链接、目录、不存在的父目录、空/缺失主文件附带遗留 WAL/SHM/journal。没有默认业务库路径，也不扫描目录。

默认只检查：

```powershell
python scripts/upgrade_agentos_c2_schema.py --workflow-db C:\维护目标\workflow.sqlite3 --checkpoint-db C:\维护目标\checkpoints.sqlite3 --identity-db C:\维护目标\identity.sqlite3
```

在相同命令后加 `--apply` 才会执行原升级器。只有操作者明确要初始化新库时，再加 `--initialize-empty`；该参数仅接受缺失或零字节文件，不会把含表但缺失前置结构的旧库当成新库。检查返回 READY 时 exit 0，存在待升级或无效组件时 exit 2；应用操作成功 exit 0，失败 exit 1 并输出错误及三库现状。本文命令仅为操作合同，本轮没有对任何真实业务路径运行它们。

现有 Workflow 必须已经具备完整兼容基础表和 Mission semantic v1，Checkpoint 必须已具备当前正式 CP 表及 version 列，Identity 必须为完整 v3；否则拒绝，交回既有对应版本的运维流程。这里不运行 Workflow 构造器去回填旧 Run，不运行 Identity 构造器去升级 v0/v1/v2 或猜测语义 key。全新空库初始化会调用原基础初始化器，创建语义前置表只表示安装 Schema，不创建 Mission/Run/语义事实，也不启用语义服务。

Schema 基准通过原构造器及原 `upgrade_schema` 在临时文件中生成，不复制另一套 SQL。比较 sqlite_master 的类型、归属和规范化 DDL，保留 SQL 引号内字符串的大小写与空白语义；内联 PK/UNIQUE/FK/CHECK、表达式/部分索引和触发器正文均参与核对。对所有目标先校验 user_version、既有组件 version、quick_check、前置结构及同名对象；Identity 另做 foreign_key_check。只有全部预检通过，才开始目标库的升级。保留未知附加表、索引和用户触发器；不 DROP、不 DELETE、不修复错误定义。缺失唯一索引前先查询历史冲突，拒绝而不删重复数据。

既有 Runtime 基础构造器仍保留历史初始化逻辑，本轮未重构这些兼容行为；尤其不能声称整个历史应用已完全消除 CREATE IF NOT EXISTS。这里证明的是 **C2 增量升级和新增运维编排不会在应用启动、装配或普通请求中执行**。现有 Identity v3 及其生命周期接线已存在，INT-1 不新增第二次接线。

## 事务、部分失败与续跑

- 原 Workflow 五阶段依次各自 BEGIN IMMEDIATE/COMMIT，版本标记与对应业务表/索引在各原事务内提交；不是一次五阶段事务。Checkpoint staged 升级也是其独立数据库内的事务。
- 在第一项写入之前检查全部三库；在每个库/Workflow 阶段开始之前再检查结构，防止把已被填充的文件当成空库。检查不是覆盖业务运行的联合 CAS，必须在停服维护窗口执行。
- 升级异常不回滚已完成阶段、不删除 Journal 行。重新运行默认检查，JSON 的 present/missing/component_versions 分别反映已完成与未完成；修正外部故障后，对原三条绝对路径重跑 `--apply`。成功的阶段由原升级器幂等核对，未完成的阶段继续。
- Workflow 已完成、Checkpoint 未完成时，不得提前 wiring C2；三库均 READY 才可进入后续接线。若数据库损坏、同名错误定义、未知版本或完整性检查不通过，必须停止并由操作者处理，不通过清库或伪造版本强行续跑。
- 新库基础初始化复用旧构造器，本身不承诺三个文件或所有基础 DDL 联合原子。已完整初始化但 ACK 丢失可识别并续跑；若死在基础 DDL 中间、尚不满足前置结构，则报告 INVALID，保守拒绝自动修复。本轮不把异常注入冒充真实进程终止。

原 C2A-1/2/3 的来源、Commit、Safe-Cut、GraphVersion、Head、Handoff、Permit、执行、恢复合同全部未修改。没有新增业务表或状态；新增的基线 JSON 仅供测试选集，不是数据库迁移账本。

## 验证范围

新增正式测试 `tests/storage/test_c2_schema_upgrade.py`，均使用真实临时 SQLite 与原初始化/升级函数：新库显式初始化、兼容库数据/额外触发器保留、重复执行、前置/版本拒绝、错误定义及 CHECK 字符串反例、部分唯一索引、Identity 外键/跨 Mission 触发器、重复历史数据拒绝、原升级事务 DDL 失败回滚、跨库部分完成与 ACK 丢失续跑、独立 CLI 进程重放，以及真实默认应用装配/普通读取不会执行 C2 升级。约束测试用原始 SQL 构造拒绝输入，仅测试 Schema，不代表创建任何有效执行许可或接受事实。

开发反馈曾有一个夹具断言错误：把 `list_missions()` 返回的 WorkflowStorePage 与列表比较，修为按真实分页合同验证 total=0。安全断言及生产代码没有为此放宽。修正后应用装配与新增约束单点 4 passed（3.72 秒）；DDL/路径/字符串拒绝 3 passed（0.89 秒）；新库初始化 ACK 丢失 3 passed（1.29 秒）。正式最终门禁的源码快照、命令、数量和实际墙钟另见下方最终证据。

冻结门禁保持 300 秒。新增源模块和 CLI 均映射到本阶段安全用例，另含既有 Identity schema 恒久合同测试；CLI 作为 external_source 独立计算摘要，未跟踪的新 CLI 也纳入变化检测。默认基线改为入场 HEAD 的 445 文件精确清单，避免把已冻结 C2A-3 改动当作本阶段新增而机械重跑；没有删除旧测试或修改旧断言、deadline、markers 及 Windows 计时精度。

## 最终门禁、摘要与文件范围

最终命令：仓库根目录 `python scripts/freeze_gate.py`。本轮仅运行一次正式门禁：**38 passed / 0 failed / 0 skipped**（本轮新增 37 项、既有 Identity Schema 合同 1 项），pytest 15.97 秒，**含启动/收集的总墙钟 21.561 秒 / 300 秒**，exit 0，状态 PASSED。Windows 默认计时，Python 3.14.5；未请求 1ms。唯一 warning 为既有 app/config.py 的 Pydantic class Config 弃用提示。没有执行全量 pytest，也没有把单点反馈通过数叠加为门禁通过数。

时间：北京时间 2026-10-22 09:26:13.605333 至 09:26:35.166759（UTC 01:26:13.605333 至 01:26:35.166759）。原始机器记录 `tmp/freeze_gate/20261022T012616Z.json`，pytest 原始日志 `tmp/freeze_gate/20261022T012616Z.log`。changed-file 清单包含新运维模块、新测试模块、新 CLI，uncovered_source_paths / missing_test_paths 均为空。最终门禁结束后只补文档，没有再次修改源码/测试/脚本。

最终 447 个 src/tests Python 文件原始字节聚合：

`9435fe271eb3988305f6ae8d69a549842fe5919f54f86c02b006fd9e0690c07d`

算法为现有 `source_snapshot()`：每个文件计算原始字节 SHA-256；按仓库相对 POSIX 路径排序，将 `路径 空格 单文件摘要` 用换行连接（末尾无额外换行），对 UTF-8 清单再计算 SHA-256。不进行 CRLF 归一化。门禁起止摘要一致。

独立脚本/基线摘要：

| 文件 | SHA-256 |
|---|---|
| scripts/upgrade_agentos_c2_schema.py | 72b55f01379900c658391cb110d142fa7de126f4d9dbea0c3d076b82c3cb08cd |
| scripts/freeze_gate.py | 083eefdd32406c020e3d0243e7bd96b52d57527d28eca33a3a2cd7b2773a2d5b |
| scripts/freeze_gate_baselines/c2b-int1-entry.json | 54ccc02a3d0ba550fffff8dd23f259460977ae0a75f3d8eea4d7c1848ce1a591 |

API 独立摘要保持 `b78ffdd8d0b1c004f9befdd63c7372070cf9a733c244f86591328897791ccc21`，未改应用 API。入场基线清单包含 445 个文件，对应 HEAD 已冻结 C2A-3 的原始工作树，不混入本阶段新文件。

本轮 6 文件范围：

- 新增 apps/agentOS/src/support/stores/c2_schema_upgrade.py：前置检查、只读差异清单、原升级器编排和可恢复续跑。
- 新增 scripts/upgrade_agentos_c2_schema.py：默认检查、显式 apply、新空库 opt-in、JSON 结果及失败后状态。
- 新增 apps/agentOS/tests/storage/test_c2_schema_upgrade.py：37 项真实 SQLite/CLI/应用装配反例。
- 修改 scripts/freeze_gate.py：本阶段源映射、未跟踪外部脚本检测及准确冻结基线；预算和断言规则未改。
- 新增 scripts/freeze_gate_baselines/c2b-int1-entry.json：入场源码清单。
- 新增本实施记录。

最终 `git diff --check` exit 0，仅有 Git 的 LF/CRLF 提示。HEAD 未变，暂存区为空；6 个阶段文件未暂存、未提交，两份入场用户审计文档原样保留。无 Push、部署、业务数据库升级、Authority 装配或正式 ADR 修改。

## 进入 INT-2 的前置条件与剩余限制

1. 操作者在独立维护窗口备份目标库，显式完成三库升级并保存 READY 检查输出；本轮没有替操作者升级业务数据库。
2. INT-2 只允许挂载已验证兼容的 Store，装配路径不得调用本运维入口或 upgrade_schema；Mission 语义服务启用仍是独立配置决策。
3. C2 五 Authority 同一规范化 Workflow 文件，staged 表使用与正式 CP 相同的 Checkpoint 文件，Identity 为既有 v3 生命周期；读取授权、来源/版本 fence 和无 Permit 不执行合同保持原样。
4. 停服/备份、跨文件非联合原子、文件替换及并发进程竞态仍是明确运维边界；不提供在线热迁移、自动降级、损坏数据修复或旧 Identity 语义回填。
5. 未执行全量 pytest、线上迁移、部署或 INT-2 wiring；本阶段测试不能作为产品人工验收或生产执行许可。


---

<!-- 原始记录：C2B-INTEGRATION-INT-1-FIX实施记录.md -->

# C2B-INTEGRATION-INT-1-FIX：证据完整性与冻结映射

状态：SELF-TESTED，等待独立验收。仅修复只读预检及测试映射，不进入 INT-2。

## 基线与范围

2026-10-22，HEAD/master、origin/master 跟踪关系及 GitHub `git ls-remote mirror refs/heads/master` 均为 `bca40b96136d0616b82b61acb3f8b1ae29d7b416`。入场工作区和暂存区为空，无切分、重置或覆盖用户工作。

入场 449 个 src/tests Python 文件聚合 `503ffa0a8565256ad7cd927a93f7843f4d7a7683812fca2c944f1d190b452367`。保留原 INT-1 基线清单，文件 SHA-256 仍为 `54ccc02a3d0ba550fffff8dd23f259460977ae0a75f3d8eea4d7c1848ce1a591`，没有重新生成基线、移动比较提交或隐藏资源变更。

本轮仅五文件：修改 `src/support/stores/c2_schema_upgrade.py`、根目录 `scripts/freeze_gate.py`；新增 `tests/storage/test_c2_schema_integrity.py`、`tests/storage/test_freeze_gate_integrity.py` 及本记录。原 `test_c2_schema_upgrade.py`、业务 Schema、Contract、CLI、资源实现、Scheduler、Binder、NodeRunner、默认生产装配和正式 Head/Permit 授权语义均未修改。

## P1：原因、真实反例与最小修复

原 `_inspect_one()` 只验证单库结构，且 GROUPS 未表达无独立版本表的 Handoff 前置关系；`inspect_databases()` 汇总结构后直接允许升级。因此 Permit Schema/记录已存在但 Handoff 表丢失时，原 Handoff 升级器可能合法建回空表；Workflow 确认事实依赖的独立 staged 表/正文丢失时，也没有跨库检查。

从真实 `GraphHandoffAuthority.prepare`、`ExecutionPermitAuthority._new_record/_reconcile`、两个 Store 及正式 Contract 重建的依赖如下：

- Permit 升级器要求 Handoff Store 已可构造，因此下游 Permit Schema/表已安装，Handoff 表却不存在，并不是原升级器正常中断的结果。
- Handoff Authority 构造前必须已安装 staged 表。STAGING 是已提交的 Workflow 意图，其正文可以尚未 COMMIT；STATE_PREPARED 则必须已有相同 staged 正文。
- 每一个 PREPARING/ISSUED/REVOKED Permit 都保留正式 handoffId、Handoff 指纹、staged checkpointId、staged 指纹、Run/Activation/GraphVersion/sourceKind/packageChecksum。PREPARING 的恢复也不能抛弃这些证据。
- Run 的既有 executionPermit 投影能证明某个 Permit 已被使用；不能因连 Permit 版本表也丢失就把授权账本视为未安装。

先保存失败反例 `tmp/c2b-int1-fix-before.log`：真实 Runtime 生成已接受、物化、激活、STATE_PREPARED 的图修订，实际执行过 A；需要 Permit 的场景通过原 Authority 签发 ISSUED，然后只在独立临时库中破坏目标表/行。原实现 **6 failed / 2 passed，7.19 秒**：4 个缺表场景误判 UPGRADE_REQUIRED，缺 Handoff 行和已确认 staged 行误判 READY。没有用无关字符串伪造成功 Permit 或执行收据。

新增 `_inspect_evidence()`，在原逐库检查之后、任何目标升级调用之前执行，只读检查：

1. 已安装 Permit Schema/表不能缺 Handoff 表；正式 Run Permit 投影不能引用缺失 Permit。
2. 复用原 Handoff/Permit Store 的反序列化、Contract、索引及 checksum 检验，核对 Permit 与已确认 Handoff 的身份/指纹/编译包绑定。
3. Workflow 已有 Handoff 时，缺 staged 表判 Checkpoint INVALID。STATE_PREPARED 必须有等同于候选的完整正文；原 staged Store 验证正文索引与 checksum。
4. STAGING 可以缺正文行，不能据此假造确认；表存在时保持原 Saga 恢复语义。尚无 Workflow 依赖事实时，Workflow 完成安装而 Checkpoint staged 尚未安装是正常的中断窗口，可以继续升级。

报错定位库、缺失表、Handoff/Permit/Checkpoint/Run ID。INVALID 由原 `upgrade_databases()` 的全库预检阻断，未进入任何目标库升级器。只做事实依赖检查，不判断当前是否有执行权限，不新建 Authority、迁移账本、证据记录或跨库事务。

永久对抗扩展到 9 类损坏：缺 Handoff 表（有 ISSUED 及仅下游空 Schema 两种）、缺 staged 表（STATE_PREPARED、ISSUED、STAGING 三种）、缺 Handoff 行、缺已确认 staged 行、staged checksum 损坏、Permit 表及标记同时丢失但 Run 投影仍在。每例都验证 inspect INVALID、upgrade 拒绝，且三个库完整 SQL dump（建表、索引、触发器与原有行）前后一致。

另有两个正例：真实安装只完成到 Activation 时可续跑；Workflow 完成但尚无 Handoff/Permit 事实时可以安装缺失 staged 表。合法 STAGING 意图与缺正文的外部提交窗口仍可保持 READY，Schema 操作不改变意图、正式图、既有 A 收据或执行状态。正常 Saga 对账仍交原 Authority 完成。

## P2：映射修复与门禁防误报

原基线以来实际差异包含资源公开入口/errors/health_store/node_health/node_store/service/sqlite_support/store、资源 Contract、Scheduler binder/leases/models、Runtime acg_execution，以及 INT-1 模块和相应测试。原解析有 9 个 uncovered source；没有移动基线。

| 源区域 | 实际相关测试 |
|---|---|
| resource/__init__、errors | 节点持久化/健康/时间异常及远端观测、认证入口 |
| resource/node_store、node_health | test_node_store：重启、跨实例健康、过期 nonce、时间异常、连续失败 |
| resource/health_store | test_health_store：共享心跳/健康指标、forced health 持久化 |
| resource/store、sqlite_support | test_store_contract：创建/CAS/nonce/凭据/原子注册/回滚；加健康/节点 SQLite 消费端 |
| resource/service | remote_observation + resource_auth + node_store：可信远端观测/序列/原子更新、注册/凭据/签名 |
| contracts/resource.py | edge_cloud_contracts + binder：画像/观测模型、资源硬约束及模型要求 |
| scheduler/binder、models | test_binder：能力/容量/模型过滤、只读 assess、真实 lease 容量 |
| scheduler/leases | test_redis_leases：原子分配、重放、到期、owner/version 续租与不可用拒绝 |
| C2 运维模块/CLI | 原升级测试 + 新证据丢失反例；原 Identity Schema 合同 |

映射测试还发现旧 `tests/runtime/test_scheduler_handoff.py` 已不存在。Scheduler 前缀映射改为真实 Binder/Redis Lease 用例；ValueStore/Run Fence 的旧悬空映射改为已有 Permit 原生执行用例，当前 Runtime/acg_execution 仍使用原 Permit 核心集合。这是替换无效路径，不是删除或跳过既有测试。

新增 19 个门禁测试：14 个路径各自验证相关测试与真实文件存在；核对整个原始基线 delta、固定基线文件摘要和去重；测试源码变化、Schema 测试失败、超时均不能报告 PASSED；模拟墙钟 301 秒时成功状态必须改为预算未完成。后三类通过受控子进程边界单测真实 `main()/write_report()` 控制流，不用真实长时间等待；SQLite 拒绝本身由前述真实库反例验证。

## 最终快照与已完成测试

最终 451 个 src/tests Python 文件聚合：`b89e62e26d26c3eca968fd2eeaa9af87d475b4f0f90a947e4be58668f287bbc1`。算法保持原 `source_snapshot()`：相对 POSIX 路径排序，原始字节单文件 SHA-256，`路径 空格 摘要` 用换行连接，再对 UTF-8 清单计算 SHA-256；不做换行归一化。

独立文件 SHA-256：门禁脚本 `05d80a198e8045bb90cf1875306ae32bebcaf89b07615ebdcbf25a6ca29f254f`；未修改的升级 CLI `72b55f01379900c658391cb110d142fa7de126f4d9dbea0c3d076b82c3cb08cd`；未修改的应用 API `2127e6e7065db1ca7179b6c5a805bb4c73d2868d5adba12431c2d76d3abe14e3`。环境为 Windows 11 build 26100、Python 3.14.5，默认计时配置。

- 定向实际命令（apps/agentOS）：`python -m pytest -q tests/storage/test_c2_schema_upgrade.py tests/storage/test_c2_schema_integrity.py tests/storage/test_freeze_gate_integrity.py --tb=short --durations=0`。**67 passed / 0 failed**，pytest 20.49 秒，含启动墙钟 **22.739 秒**，exit 0，源码未变。证据 `tmp/c1_audit/c2b_int1_fix_target.log/.json`。
- `python scripts/freeze_gate.py --dry-run`：exit 0，uncovered_source_paths=[]、missing_test_paths=[]，diff check=0；仍比较原 INT-1 基线。机器选集 `tmp/c2b-int1-fix-dry.json`。
- `python scripts/freeze_gate.py`：**174 passed / 0 failed / 0 skipped**，总墙钟 **32.614 秒 / 300 秒**，exit 0，PASSED，源码起止相同。证据 `tmp/freeze_gate/20261022T033129Z.json/.log`。没有增大预算、删减慢测试规则或改 deadline。
- 扩大回归（apps/agentOS）：`python -m pytest -q tests/components/resource tests/components/scheduler tests/storage tests/contracts tests/architecture --tb=short --durations=10`。**245 passed / 0 failed**，pytest 22.91 秒，总墙钟 **25.035 秒**，exit 0，源码未变。证据 `tmp/c1_audit/c2b_int1_fix_expanded.log/.json`。
- 外部 API：`python scripts/verify_mission_semantics.py apps/agent/tests/test_agentos_v2_api.py`，**52 passed / 0 failed**，pytest 11.75 秒，总墙钟 **13.856 秒**，exit 0，源码未变。证据 `tmp/c2b-int1-fix-api.log/.json`。复用现有脚本隔离 cwd、环境与临时库，未扫描/清理用户旧临时目录，也未把 API 结果混算进 174 项冻结门禁。
- 完整 AgentOS 回归（本轮用户明确授权，apps/agentOS）：`python -m pytest -q --tb=short`。**1992 passed / 0 failed / 0 skipped**，3 warnings，pytest 1037.91 秒，总墙钟 **1040.474 秒**，exit 0。UTC 2026-10-22 03:36:23.812461 至 03:53:44.286922（北京时间 11:36:23.812461 至 11:53:44.286922），451 文件及外部 API/CLI 摘要起止完全一致。证据 `tmp/c1_audit/c2b_int1_fix_full.log/.json`。未传 marker 过滤、未请求 1ms、未修改原 timeout，按完整默认选集执行。该 17 分钟深度回归独立于 32.614 秒冻结门禁，不冒充五分钟内完成全量。

本轮无因预算或环境遗漏而待补的已要求测试批次；没有 INCOMPLETE 批次。各批次存在重叠，不相加声称独立用例总数。全部最终结果对应同一最终源码快照；只在测试完成后补报告文字。

开发期间曾有新增门禁测试夹具漏提供 subprocess.STDOUT 的错误，补全替身后控制流测试通过；原不存在的 Scheduler 测试路径由永久映射测试识别并修正。没有为了通过反例而弱化数据库或执行断言。全部最终结果只归属于上述最终快照，中间失败日志不充当最终通过证据。

## 外部 API 工作流与剩余边界

AgentOS pytest.ini 的默认 testpaths=tests 不包含 `apps/agent/tests/test_agentos_v2_api.py`，本次冻结门禁也不覆盖它。已有 `scripts/verify_mission_semantics.py` 的 **audit** 集合显式包含该文件；默认 api 集合不包含它。GitHub 当前只有 backend-ci.yml 的 Maven 门禁，不等于自动执行 Python API 验证。本轮使用既有隔离脚本仅运行该文件，结果另记，不扩大冻结门禁职责。

本预检仍需要停服维护窗口。不同数据库、不同只读连接不具备联合 CAS/联合快照；不能抵御在线业务或管理员在检查后删除证据。没有声称 READY 能授权激活、派发或恢复，也没有检查/修复所有业务数据的语义真实性；当前检验的是已存在授权账本所需的结构及持久证据依赖。历史证据的 GC/归档协议不在本轮，不能自行清理以绕过拒绝。

最终 `git diff --check` exit 0（仅 Git LF/CRLF 提示）；HEAD 保持入场提交，暂存区为空，五个阶段文件均未暂存/未提交。未修改基线清单、用户既有文件、业务数据库或默认生产接线，未 Commit、Push、Merge、部署。可申请本阶段独立验收；本报告不宣布 ACCEPT，不授权进入 INT-2 的生产装配。


---

<!-- 原始记录：C2B-INTEGRATION-INT-1-FIX2实施记录.md -->

# C2B-INTEGRATION-INT-1-FIX2 实施记录

日期：2026-10-22。范围仅为冻结门禁基线完整性与 Schema 预检证据关联；不改变执行授权合同，不进入 INT-2。

## 1. 入场与保护范围

- 本地 `master` / HEAD：`25bc3b956310737ebcb224c37dababd659bedd2c`。本轮用 `git ls-remote https://github.com/zongxi-Li/zhiyi-AgentOS-2026.git refs/heads/master` 确认 GitHub 同 SHA，`HEAD...origin/master` 为 `0 0`。暂存区为空。
- 入场 AgentOS src/tests 为 451 个 Python 文件，聚合 SHA-256：`b89e62e26d26c3eca968fd2eeaa9af87d475b4f0f90a947e4be58668f287bbc1`。此前提交和测试均只作历史依据，不冒充本轮验证。
- 操作中发现前端并行工作：`apps/frontend/components.d.ts`、`apps/frontend/src/components/agentos/AcgTopologyGraph.vue`，以及未跟踪的 `apps/frontend/src/utils/acgExecutionLayout.ts` / `acgExecutionLayout.spec.ts`；diff 检查还出现自动导入声明的换行提示。均保留，不编辑、不暂存、不纳入本轮范围。README、EX-00、图片及其他用户工作均未清理或覆盖。
- 原基线 `scripts/freeze_gate_baselines/c2b-int1-entry.json` 未修改：原始字节 SHA-256 为 `54ccc02a3d0ba550fffff8dd23f259460977ae0a75f3d8eea4d7c1848ce1a591`，445 项 manifest 聚合为 `cb5809b8a2e29278d39d6ab70c6bd1567da7073148195201d013f1105f9a2c47`。

## 2. 失败反例与根因

### 门禁基线

`changed_python_paths()` 原先在基线不存在时回退 Git HEAD；干净工作区可能因此返回无变化成功。已存在的 JSON 未认证其固定内容，即便重算 aggregate 也可以替换比较对象。外部 API/CLI 只比较 HEAD，遗漏已提交变化；门禁自身也不在源码集合内。

修复前命令（pytest 的工作目录均为 `apps/agentOS`）：

```text
python -m pytest -q tests/storage/test_freeze_gate_integrity.py -k "untrusted_baseline or missing_default or committed_external" --tb=short
```

8 failed / 19 deselected，pytest 3.74 秒、启动器墙钟 7.051 秒。四项是基线缺失/篡改/aggregate/替换未拒绝；默认缺失入口抛未结构化异常；三项为固定外部比较能力缺失。后者是新增接口尚不存在的红灯，不把 KeyError 本身夸大为生产数据损坏。原始记录：仓库 `tmp/c1_audit/int1-fix2-baseline-before.{log,json}`。

### Run—Permit 语义关联

`_inspect_evidence()` 原先只确认 Run 引用的 permitId 存在。独立 Permit/Handoff checksum 校验不足以证明该 Permit 属于这个 Run/Mission/正式 Head。

新增 `two_permits` 夹具使用同一 Runtime、两个 Mission 和同一 Workflow SQLite，分别经过真实接受、Initial 物化、Activation、Handoff 和 ISSUED Permit。两条图身份不同。仅损坏注入使用 SQL，真实成功事实均由既有 Authority 产生。

稳定复现命令：

```text
python -m pytest -q tests/storage/test_c2_schema_integrity.py -k "semantic_identity or two_valid" --tb=short
```

修复前 6 failed / 1 passed / 11 deselected，pytest 28.91 秒、墙钟 30.586 秒。六个失败均为预期 `INVALID`、实际 `READY`：完整交叉 Permit 投影、Permit Mission 篡改、Permit Graph 篡改、投影 GraphVersion/Activation/Handoff 篡改。Mission/Graph 两项重新计算合法 checksum，并断言正式 typed Store 仍能读出记录，证明拒绝必须来自身份关联而非 checksum 失败。原始证据：`tmp/c1_audit/int1-fix2-identity-reproduced.{log,json}`。

构造夹具的首轮曾因 `execution_permit_projection` 导入位置错误而失败，已修正为正式 contract 导出；`int1-fix2-identity-before` 属于夹具失败且测试期间文件变化，不能用作生产缺陷或最终快照证据。以上稳定复现才是修复依据。

## 3. 实际修复

| 文件 | 行为 |
| --- | --- |
| `scripts/freeze_gate.py` | `load_baseline()` 认证固定文件 SHA、数量及 aggregate；缺失/损坏/替换返回 `BLOCKED_BASELINE_INTEGRITY`，在测试发现及启动前终止。取消 HEAD 回退。运行后复查基线，变化返回 `INCOMPLETE_BASELINE_CHANGED`。 |
| 同上 | API、CLI、门禁自身与原 INT-1 入口的固定内容比较，不随当前 HEAD 前移；脚本变化映射到完整性测试，缺失外部源码阻断；纳入运行前后源码保护和报告。预算仍为 300 秒。 |
| `src/support/stores/c2_schema_upgrade.py` | 在只读 Workflow 事务内读取完整 Run，核对行索引身份，复用 `validate_activation_run()` 验证 Run→Head→Activation→Materialization→Permit→Handoff 和完整 Permit 投影；错误包含 Run/Permit 定位。另补 Handoff candidateGraph.graphId 与 Permit.graphId 对应检查。 |
| `tests/storage/test_freeze_gate_integrity.py` | 基线篡改/删除/替换、默认入口拒绝、三个外部源码已提交变化、门禁单独变化及测试运行期间基线变化的永久反例；既有超时和失败断言保留。临时真实 Git 仓库验证 `git diff HEAD` 为空仍能发现固定基线差异。 |
| `tests/storage/test_c2_schema_integrity.py` | 两条真实 Permit 链的身份错配与重算 checksum 反例；拒绝升级后 Workflow/Checkpoint/Identity 三库完整 SQL dump 相同；有效双 Run 正例、合法 Native 执行后 Checkpoint 推进正例。 |

没有修改 `validate_activation_run`、Permit Authority、Head、Handoff 或 Runtime 的生产授权语义。预检调用的是既有只读校验函数，不建立第二套 Authority。无依赖事实的中断安装与合法 STAGING 窗口仍由原测试验证可恢复。

外部比较锚点仍是 `09860f8c88c4b8d40cac2c80ca836f0bfa5a2c35`。API 原 Windows 工作区 CRLF 字节 SHA 为 `b78ffdd8d0b1c004f9befdd63c7372070cf9a733c244f86591328897791ccc21`（原 Git LF blob 为 `1b3d89fe60f77c9ca1e61985d6ada70e2651836b6b4157ca1d22321d28f9275d`）；门禁原 LF 字节 SHA 为 `06816f400a6d5a6143ead0f9d32af1d70a2715202cbbcd7223e05df1469d0637`；升级 CLI 当时不存在。只补这些外部锚点，未重新生成原 manifest。

## 4. 测试与最终快照

环境：Windows 11 build 26100，Python 3.14.5，默认计时环境；未请求 1ms，未修改 deadline、预算、marker 或既有断言。所有数据库实验均为 pytest 临时 SQLite，不连接真实业务库。

开发反馈：

1. 修复主体后，`python -m pytest -q tests/storage/test_c2_schema_upgrade.py tests/storage/test_c2_schema_integrity.py tests/storage/test_freeze_gate_integrity.py --tb=short`：82 passed，pytest 51.01 秒、墙钟 53.220 秒，退出 0。当时 src/tests 摘要 `c87bcb005b0012b86f3c08b8096e3865754d3984deff1d7ade2ba106c21bf895`，是增加最后两项保护测试之前的中间快照。
2. 最终补充测试后，精确运行 `test_gate_never_reports_success_for_changed_sources_failed_preflight_or_timeout` 及 `test_preflight_accepts_legal_native_checkpoint_advancement`：5 passed，pytest 6.37 秒、墙钟 8.636 秒，退出 0。使用下述最终快照。
3. `python scripts/freeze_gate.py --dry-run`：退出 0，0.259 秒；26 个固定基线差异路径映射至 16 个测试文件；未覆盖源码、缺失测试、缺失外部源码均为空，diff check 为 0。原始结果 `tmp/int1-fix2-dry-run.json`。

最终正式门禁（只执行一次）：

```text
python scripts/freeze_gate.py
```

- `PASSED`，退出 0；230 passed，0 failed / errors / skipped / deselected，2 项既有弃用警告（Starlette TestClient/httpx、Pydantic class-based config）。
- pytest 153.21 秒；门禁完整墙钟 **160.616 秒**（外层启动器 160.794 秒），未超 300 秒。
- 历史测试耗时已知项总和为 75.510 秒，未知项列于报告，没有以未知耗时当作零成本承诺；实际超时保护保持原样。
- 16 个测试文件的 230 个唯一 node ID 全部完成；包括本轮新增 17 项反例/兼容性测试、全部 Schema 升级/完整性用例、既有 Permit、资源、Scheduler、流式调用、Identity Schema、C1 纵向恢复与交付回归。未覆盖源码、缺失测试、缺失外部源码均为空。
- 最终源码与外部源码前后相同；基线运行前后均认证通过。最终快照与下面摘要相同。`git diff --check` 通过（退出 0，只有 Windows LF/CRLF 提示）。
- 原始日志：`tmp/freeze_gate/20261022T115641Z.log`；门禁完整 JSON：`tmp/freeze_gate/20261022T115641Z.json`；外层 stdout：`tmp/int1-fix2-freeze-console.json`。这些 tmp 证据未暂存。

本轮不运行全量 pytest，不用此前全量结果代替本次验证。开发期中间快照的 82 项结果单独列出；最终门禁重新覆盖这三份测试文件及新增正例，避免将中间结果充当最终结果。

最终 src/tests：451 个 Python 文件，SHA-256：

```text
49a91f777b2d5cc520b0374ddedc26f5b385e3d8ad8bbbdc7db3816a319c913a
```

算法与既有门禁一致：每个 src/tests `.py` 原始字节计算 SHA-256，按仓库相对路径排序，组成无结尾换行的 `path digest` 行序列，再对 UTF-8 序列计算 SHA-256。完整逐文件 manifest：`tmp/int1-fix2-final-snapshot.json`。该文件和原始日志在本地 tmp，不作为源码提交。

最终外部源码 SHA-256：

| 路径 | SHA-256 |
| --- | --- |
| `scripts/freeze_gate.py` | `4405b0b923d828574712e867fa1c40b6a6e90103e362f23889986940b277015e` |
| `scripts/upgrade_agentos_c2_schema.py`（本轮未改） | `72b55f01379900c658391cb110d142fa7de126f4d9dbea0c3d076b82c3cb08cd` |
| `apps/agent/app/api/agentos_v2.py`（本轮未改） | `2127e6e7065db1ca7179b6c5a805bb4c73d2868d5adba12431c2d76d3abe14e3` |

## 5. 限制与状态

- 预检是运维维护窗口下的只读一致性验证；Workflow 内关联使用同一读事务，后续分库读取和 DDL 仍无联合原子性，须停止并发业务写入。既有跨库限制未消失。
- Schema 预检不等于实时执行授权、所有历史 Receipt 的真实性证明或通用恶意数据库取证；本次验证的是被 Run 采用的 Permit 链和已有 Handoff/Checkpoint 依赖完整性。没有修复或补造丢失证据。
- 原始字节固定基线采用保守策略，换行或格式变化也会阻断/触发回归。`--baseline` 只允许定位同一已验收文件的精确副本，不允许任意移动验收基线。
- `apps/agent/tests/test_agentos_v2_api.py` 不在 AgentOS 门禁直接测试目录，本轮未单独执行；API 差异触发的是既有 C1 纵向与交付测试。全量、生产装配、部署及业务库升级均未验证或执行。
- 最终状态只标记 SELF-TESTED，等待独立复验；不自行声明 ACCEPT。


---

<!-- 原始记录：C2B-INTEGRATION-INT-1-Permit反向关联修复实施记录.md -->

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
