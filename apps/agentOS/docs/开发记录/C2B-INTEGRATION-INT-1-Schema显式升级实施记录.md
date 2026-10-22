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
