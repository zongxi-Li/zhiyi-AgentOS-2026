# PR-S03-01 Durable Graph Materialization Transaction

## 状态与基线

S03-01 最小无控制 DAG 物化路径实施与自测完成，等待独立架构验收，不宣称 ACCEPT。本轮保持未提交，不 Push、部署、升级业务数据库或修改正式 ADR。

入场 master / HEAD：`37613122cc7b1de1f502ad61beb6756b90b498ef`，工作区与暂存区均干净。以 S02-03 独立报告的修复后代码为基线；冻结的 11 文件工作区摘要 `edf59d1c57715d22bad5ba832606bf15fbe532df61e2f31035c9d535c80d1164` 对应上阶段 ACCEPT。保留全部 S02-02/S02-03 原测试及断言。

## 入场勘察与最小方案

PlanningCommitService 是唯一规划接受权威，SQLitePlanningCommitStore 保存不可变 Record 和原子 outbox；本阶段不改写接受事实，也不新增规划接受路径。

ACGLowerer 决定逻辑实现和完整候选图，S02-03 已在 Commit 中冻结 candidateGraph/nextPlan/nextBindings/graphPatch/sourceProvenance/SafeCutProof。本阶段不重新运行 Lowerer、Planner、LLM 或语义决策。既有 ACGGraphCompiler.compile_package 是纯 Blueprint→V4 Package 边界：输入完整 Blueprint 和明确 Run ID，输出确定性节点/依赖及控制、绑定、技能、记忆、证据、通信清单；它不查询可变目录、不创建资源或执行任务。Compiler.compile 进一步构造内存 ACGExecutionGraph，本阶段不需要调用；仓库没有另建名为 RuntimeGraph 的正式状态系统。

SemanticRevisionService.prepare 不落最终转换事务，但会生成 replacement Run ID、重建全新执行态、同步步骤并编译替换包，不能作为本阶段的物化入口。commit 会写 ExecutionValueStore 图补丁、Identity/谱系、Run 正式 Blueprint/Package、SUPERSEDED 状态和 Workflow 转换 outbox。最终 save_graph_patch_transition 用 BEGIN IMMEDIATE 持久替换 Run 与源 Run。本阶段不调用 prepare/commit，只复用其无 IO 的静态 _validate_bindings（完整覆盖和既有语义保持校验）。

RuntimeBindingService.prepare 会登记嵌入式 Agent 资源、写 execution requirements；ResourceBinder/Scheduler 才决定真实资源和派发。本阶段均不调用。Identity compile 适配器需要已登记 Blueprint/Run，register_blueprint 会创建正式 Identity 记录，因此也不借道该路径。

实现前选择的方案：显式 Runtime Authority + 独立 inactive Journal；Journal 与规划 ledger/Run/Mission 在同一个 Workflow SQLite。昂贵编译在事务外，提交前使用相同连接重读 ledger、Run/Mission 并复用 S02-03 来源/Safe-Cut 校验。仅新建一个不可变 Journal 行，不需要 PREPARING 状态、额外 outbox 或跨库写阶段。

## 合同、读写权威与调用链

新增 `contracts/graph_materialization.py`：extra=forbid/frozen；GraphMaterializationRecord 保存版本、materializationId、idempotencyKey、sourceCommitId、完整接受记录指纹、Mission/源 Run/Graph、原/候选 GraphVersion、FrozenPlanningSources、当前验证策略、Proof 指纹、完整 CompiledACGPackage 和 packageChecksum。唯一记录状态为 MATERIALIZED_INACTIVE。Receipt 的 IDEMPOTENT_REPLAY 仅报告历史物化身份；REJECTED 使用既有结构化拒绝码。

Package.runId 绑定源 Run，作为确定性编译命名空间及来源身份，不创建第二个 Run，也不是授权该源 Run 执行下一版。candidateGraph 仍由唯一不可变 GraphRevisionProposal 完整保存；Journal 引用该 Commit 及其整体指纹，不用 GraphPatch 三元投影替代完整图、不复制另一套 TaskPlan。Package 内的逻辑 binding/communication manifest 不是物理资源租约。

真实链路：

`ExecutionRuntime.materialize_graph_revision(commitId, idempotency_key) → GraphMaterializationAuthority → 唯一 ledger Record → 当前来源/完整接受链/Safe-Cut → 原静态 bindings 校验 → ACGGraphCompiler.compile_package → Record/checksum → Run lock → Workflow BEGIN IMMEDIATE → 最终来源/权限/链/Safe-Cut → Journal INSERT → commit → Receipt`。

客户端/模型没有 package、candidateGraph、proof、Run ID、权限或预算参数。enable_graph_materialization 是显式服务端装配，默认 authority=None，无新 Feature Flag、API、默认生产装配或 outbox 消费者；缺物化或规划 authority 均拒绝，不回退旧修订流程。Journal 构造时检查与 Workflow/Planning ledger 同一绝对 DB 路径。

## 当前验证及事务

1. 从 typed ledger 读取 graph_revision，重算既有 Proposal 指纹，要求 parent=source plan_revision、revision 相邻、Mission/revision/Plan/Graph/Observation 一致、source_provenance 一致、GraphPatch base version 正确，且当前接受头就是该 graph Commit。向上读取完整祖先，检查同 Mission/相邻 revision/根 revision=1；循环、缺失或超过 256 层明确拒绝。
2. 复用 GraphProvider.get_current_sources、source_provenance、safe_cut：重新检查 Frozen Basis/scope、Workflow 全正文、目录/profile、Identity Plan、Observation、正式 Plan/Graph、步骤/attempt/输出/收据、最新已确认 Checkpoint、审核及控制屏障。PROVEN 本身不免除当前验证；历史 v1 来源不能冒充 v2。
3. 当前身份必须与编译前相同，授权、取消和 authority 在来源读取后关闭 Fence。纯 Compiler 只消费本次从不可变 Record 反序列化的完整图与固定 Run ID，不再采样 Registry 或资源状态。
4. 在事务外验证 nextBindings 完整覆盖及语义保持；用原 Compiler 生成 Package。复用 Compiler 的 checksum 输入映射（嵌套模型由 stable_checksum 排除默认值）校验正文和确定性 packageId；BlueprintHash 使用 Compiler 的完整 alias JSON 投影，不混用另一个摘要算法。Journal 最大 4M JSON 字符。
5. 最终锁顺序为 Run Lock → Journal/ledger transaction lock → BEGIN IMMEDIATE；没有逆序。最终事务不运行 Compiler/Lowerer。重验实际 Schema、当前接受记录及接受头、全部来源与 Safe-Cut、当前身份/权限/取消，随后只读取同库幂等索引并插入已构造的固定正文；不再读取外部可变来源来决定持久化内容。
6. Journal 行以 materialization_id 主键，idempotency_key、source_commit_id 各有正式 UNIQUE 索引。相同 key/相同内容返回同一结果；不同 Commit 复用 key 或同 Commit 不同 key 拒绝，不产生第二行。并发计算可重复，唯一持久化提交点只有 conn.commit。

同 key 重启重放不重新编译，但仍验证当前来源/权限/接受头及 Journal 正文；发生漂移时保守拒绝，而不是把历史成功当成当前许可。提交成功而响应丢失，原 key 在仍满足当前验证时返回同一 materializationId；只读 Journal 查询仍可对账已提交事实。

## Schema 与恢复隔离

新增 `support/stores/graph_materialization_store.py`，复用既有 SQLite 连接/事务纪律，不改 PlanningCommitStore。显式管理入口 upgrade_schema 要求规划 ledger 已准备；创建独立 schema(version=1)、Journal 表及两个唯一索引。管理事务及构造器都检查版本和表/索引实际 SQL 定义，名称相同但非 UNIQUE、错误列或缺失定义均拒绝；错误定义不自动修复。构造器仅 mode=rw 查询，不创建数据库、不执行迁移。所有管理操作只在临时测试 DB 执行。

Journal 读取同时校验 typed Record、package checksum、整行 checksum 和索引列身份。写前错误、AFTER INSERT 故障均全回滚；commit 成功/ack 失败留下一个完整 inactive 行，原 key 可重启对账，没有半成品可执行状态。

数据库差异比较包含 Workflow、Identity、value、checkpoint、provenance 等 fixture DB，扣除 Journal INSERT 后应完全相同；接受 ledger/outbox、正式 Run/Plan/Graph、执行收据、Checkpoint、资源与 Agent 调用均不因物化改变。真实 Runtime wait/recovery/review 集成证明：恢复不采用 inactive package；普通批准仍执行原 v1 图、仅调用原 A，Journal 保持 inactive。

S03-01 只验证当前 GraphVersion 与源绑定版本相等，并记录预计下一版；不更新正式 Active GraphVersion，不创建 Scheduler 可领取任务，不替换/终止源 Run。S03-02 才拥有重新验证后的激活 CAS 与执行生命周期交接。

## 失败反例与自测证据

初版新增 26 项：9 failed / 17 passed，30.85s。其中合法物化失败定位到新合同误用 checksum 规范化：Compiler 的嵌套模型输入和展开 JSON 的默认字段不同；按 Compiler 原始映射修复，不改原 Compiler。另一个失败是测试误把缺物化 authority 当成禁止旧图执行；分开验证新入口 fail-closed 与既有 planning authority 恢复屏障，未改变生产 Runtime 执行行为。

第二轮 1 failed / 25 passed，23.44s：不同 key 重复物化虽最终拒绝，但仍重新编译，命中“重放不得再编译”的对抗检查。加入事务外只读已物化来源检查，最终事务保留同样的唯一性复核；修复后扩展 35 项全部通过，37.39s。

中间快照 1460ca54fd3b 的定向集 287 passed，167.50s；其扩大运行期间尾项审查发现最终身份提供器回调在授权之后执行的漏检窗口。先补反例 `-k final_identity_callback`：1 failed / 41 deselected，2.71s，身份回调设置取消信号后初版仍 MATERIALIZED_INACTIVE。最小修复是提前捕获身份、随后关闭权限检查，再复核取消和两项 authority 身份，不修改 S02 来源算法；修复后两个关闭窗口测试 2 passed / 40 deselected，3.96s。已核实本任务 pytest 20172 及父 PowerShell 命令中的专属日志路径后停止中间扩大进程，未触及其他进程；该运行无最终汇总，不算最终证据。最终三组从头重跑。

最终命令在 apps/agentOS，Python 3.14.5 / Windows 11 默认计时，不请求 1ms、不修改/跳过/放宽原测试：

```powershell
python -m pytest -q tests/components/planner/test_graph_materialization.py tests/components/planner/test_graph_revision_commit.py tests/components/planner/test_graph_revision_audit.py tests/components/planner/test_planning_commit.py tests/components/planner/test_planning_commit_runtime.py tests/components/planner/test_planning_commit_audit.py tests/contracts tests/architecture --tb=short
python -m pytest -q tests/components/planner tests/contracts tests/architecture tests/runtime --tb=short
python -m pytest -q --tb=short
```

最终新增集 42 项，包含合法完整包、已完成前缀、同 key/不同 key 跨连接竞争、重启重放、源接受头与 key 内容冲突、取消/撤权/新收据/操作员输入/Checkpoint/Plan/Graph/身份/目录/Workflow/authority 变化、包/候选/绑定/来源损坏、完整接受链损坏、真实审核/恢复隔离、显式 Schema 与错误唯一索引、写前/事务中/commit ack 故障及最终授权关闭窗口。

| 最终源码上的范围 | 实际结果 |
| --- | --- |
| 上述定向 + contracts + architecture（含新增 42 项） | **288 passed，174.80s（2:54）** |
| 扩大回归 | **887 passed，653.50s（10:53）** |
| 全量 | **1502 passed，1 warning，461.34s（7:41）** |

最终测试前固定 5 个 Python 文件，路径相对仓库根，按路径排序，每行 `path + 空格 + sha256(文件原始字节)`，LF 连接后 SHA-256：`6af0de62c94b2974ce56cf1a63221bd86e04fbba5874c99ad8eb8f628dcd06bf`。文档不参与源码摘要。

| 文件（相对 apps/agentOS） | 文件 SHA-256 |
| --- | --- |
| src/contracts/graph_materialization.py | 4b07353894598f6b7ecdd3180ae616f902f072d3999160ba3e859e8c17b8a0b7 |
| src/runtime/graph_materialization.py | d81671a9129cf216c36d024b2e85ed80ae008c1089361112109372b6e8ef73aa |
| src/runtime/workflow_runtime.py | 6dd0aa76a2fd62274ce25ff1d5e6cd2e62f8ea169316ea3df18c0b6e8b0b7524 |
| src/support/stores/graph_materialization_store.py | d694993674870be966ed942747f1af5298554f969514f241c0ed2f4c4946a334 |
| tests/components/planner/test_graph_materialization.py | 5c6e394d1afa9732915e6e35e431777c53257e98522b31c69b9cf76c26e1e6c1 |

源码清单保存在系统临时目录 S03-01-source-snapshot.json；定向/扩大/全量完整输出分别写入 S03-01-final-targeted.log、S03-01-final-broad.log、S03-01-final-full.log。三组均在上述最终快照执行，期间无源码修改。最终 1502=冻结基线 1460+新增 42，唯一 warning 为原 PyPDF2 弃用提示，0 failed、0 skipped；没有请求 1ms 或修改既有 20ms 流式测试。

最终源码摘要复核与上表一致；git diff --check 通过。HEAD 仍为 37613122cc7b1de1f502ad61beb6756b90b498ef，暂存区为空，工作区仅 1 修改（Runtime 显式入口）+5 新增（合同、Journal、Authority、测试、本记录），全部属于 S03-01。没有修改任何 S02-02/S02-03 测试或冻结修复。

## 保留限制与 S03-02 前置条件

- 范围仅 graph_revision、无控制 DAG。initial_plan 需要不同 Run 创建/来源流程，本轮不接入；HTN/Horizon durable 消费、通用 branch/loop/join Safe-Cut 不开放。
- 单进程 Run Lock；跨连接依靠 Workflow SQLite BEGIN IMMEDIATE。Identity/value/checkpoint/目录与 Workflow 没有联合事务，最终检查到提交之间仍有跨库/内存源竞争窗口。物化只产生不可执行的历史事实，S03-02 必须再次验证，不能凭成功回执激活。
- 原来源验证的数量/体积上限继续有效；Journal 另有 4M 字符界，接受祖先最多 256 层。同步解析/Compiler/来源验证没有可抢占硬 deadline；输入读取先于部分限制，单项深度/外部 Checkpoint 总字节仍无统一硬上限。Compiler 在事务外，但最终来源 IO、序列化、Safe-Cut 和祖先查询仍占全库写锁；不承诺跨 Mission 吞吐上限。
- Schema 定义检查有意严格，等价但正文不同的管理定义也可能拒绝，需管理员明确处理；本轮不升级任何业务库。既有 Planning ledger 对同名错误索引的 P2 不在此重构，新 Journal 两个唯一索引则检查完整定义。
- commit ack 故障用实际提交后抛异常模拟；未执行进程 kill、断电/WAL 损坏或分布式多实例实验。重启验证为新服务/新 SQLite 连接重新读取持久正文，不宣称已完成全部生产灾难恢复验收。
- S03-02 应从 Journal 和不可变 Commit 链读取完整包/图/计划/绑定，验证两套正文摘要、当前接受头、当前编译与 Safe-Cut 策略、权限/Basis/scope、正式 Plan/Graph、收据/Checkpoint/审核/控制；确定源 Run/下一版执行身份、已执行前缀及外部副作用的复用合同，然后建立正式 GraphVersion CAS、激活原子提交、幂等恢复及 Scheduler 交接。不得重置 receipts 或隐式重执行已完成副作用。

变更范围：新增合同、Journal store、Runtime Authority、新增集成测试及本记录；workflow_runtime.py 只增默认关闭的 authority 字段和两个显式入口。未改 Compiler、Lowerer、SemanticRevisionService、Scheduler、Executor、S02 接受服务/Schema、正式 ADR 或生产配置。
