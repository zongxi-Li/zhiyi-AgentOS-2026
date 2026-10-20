# PR-S02-03 Graph Revision Commit 与 Safe-Cut

状态：最小 DAG 范围内实施与最终自测完成，等待独立代码级验收；全部修改未提交。控制图切口保守拒绝，不声称完整支持或独立验收 ACCEPT。

## 基线与真实权威链

入场 HEAD 为 S02-02 冻结提交 `1b508748535b211afcb0546ae2c216a83daeca47`，工作区、暂存区干净。已读取 S02-02 独立报告及真实实现；原始提交 `66249bbe` 的六类 P1 修复保留，既有测试目标不变。

真实链路：

`TaskPlanPatch → PlanningCommitService → durable plan_revision Record → Runtime.accept_graph_revision → 可信来源预检 → SemanticGraphPatchService.apply → 原 Topology Compiler → 原 ACGLowerer → derive_graph_patch → Safe-Cut → PlanningCommitService → 同一 ledger / 原子 outbox`。

SemanticGraphPatchService.apply 仅调用语义 patch 校验与纯下沉；derive_graph_patch 仅计算 diff。SemanticRevisionService.prepare 则会分配并构造 replacement Run、同步步骤、编译执行包；commit 会写 value store graph patch、替换 Run、谱系与正式状态。因此本轮完全不调用 SemanticRevisionService.prepare/commit，也不调用 Runtime Binder。ACGLowerer 保持全节点覆盖，未修改共享 Topology Compiler、Scheduler 或执行控制引擎。

## 最小方案与合同

- `contracts/graph_revision.py`：PlanningSourceProvenance、SafeCutProof、GraphRevisionProposal，extra=forbid/frozen，显式版本化。复用原 TaskPlan、TaskImplementationBinding、GraphPatch、RuntimeBlueprintSpec，不复制正式计划或图合同。
- PlanningCommit 的 ProposalType 增加 graph_revision，Record 保存可选 sourceProvenance；proposalPayload 可包含完整 GraphRevisionProposal。请求仍没有 run_id、executor、permission 等客户端权威字段。
- GraphRevisionProposal 绑定源 commitId、Mission/revision、源 Proposal 内容指纹、源 Run/Graph、原 PlanVersion、Frozen Basis/scope 摘要、Compiler 版本、下沉/验证/来源投影版本。GraphPatch 中明确 baseGraphVersion 与候选 version=base+1。
- 新语义修订接受时由 Runtime 注入 `runtime-static-v1` 证明。包含 Run 输入、Basis、scope、原 Plan/Graph/编译包/绑定、步骤、完整已知收据、规范化控制执行态、能力目录、逻辑 Agent profiles、Identity snapshot、操作员 inbox。只剔除 plain planner wait 改变的 checkpointId/reviewPayload/currentStepId，并单独验证这些当前证据；原 Observation、Plan/Graph 版本必须仍对应。
- 已冻结旧 Record 不更新。没有 provenance 的旧语义修订明确拒绝派生；未知 provenance/Compiler 版本不能冒充当前版本。新来源投影 version 与 S02-02 旧 strategyFingerprint 分开，不重新解释历史指纹。
- 返回仍为 PlanningCommitReceipt。Record.status=ACCEPTED，materializationStatus=COMMITTED_NOT_MATERIALIZED；候选图 version 是正文的一部分，不修改正式 GraphVersion，不代表 APPLIED。

## 存储、CAS 与唯一来源

复用原 planning_commit_records/outbox、全字段请求摘要、Mission commitmentRevision CAS 和 BEGIN IMMEDIATE。parentCommitId 为源 plan_revision；派生新接受时源必须仍为 Mission 接受头。没有第二个接受服务或接受事务。

在显式 upgrade_schema 中增加 partial UNIQUE expression index `planning_graph_source_unique`，约束 graph_revision 的 proposalPayload.sourceCommitId。没有新表或正式图状态系统。事务内还查询已有图修订：同 key 原样重放；不同 key 不给同源再接受第二份图。不同 Source 或 Run 复用同 key 拒绝。

构造器不自动 DDL；旧无 index 的 v1 ledger 可读、可继续原语义接受，但新图接受返回 STORAGE_UNAVAILABLE，需显式准备 index 后重开 store。测试只在临时 DB 调用该管理入口，未升级业务 DB。旧 Record 原始 JSON 在新图接受前后逐字节不变。

昂贵语义预检、拓扑和下沉均在 ledger 写事务外；下沉也在 Run 锁外。最终接受：Run lock → SQLite write transaction → 当前 Sources/权限双检 → 源 commit/接受头验证 → 已认证派生摘要与当前 Safe-Cut 证据比对 → 原 CAS/append/outbox。保留原锁顺序，没有反向取得 Run 锁。

最终事务不重跑 Topology Compiler。Runtime 内部 provider 仅认可本次纯推导生成的私有摘要证书；客户端构造一个 schema-valid GraphPatch 或 proof 不足以通过。历史重放无需再次下沉，但必须当前授权，且没有执行许可。

输入政策：最多 256 步骤、1024 原图边、1024 收据、64 inbox 输入、256 Agent profiles、512 能力描述；来源 Run / 完整候选各最多 2M JSON 字符。同步读取和验证无可抢占硬截止期；跨 DB 最后一次检查到落盘的间隙仍非联合事务，不能宣传为解决跨数据库原子性。

## Safe-Cut 范围

允许最小的无控制 DAG 修订；执行事实不变、静态有效依赖不变的 pending 后缀/独立扩展可接受。

保护 completed/failed/cancelled/skipped/non-pending、attempt/retry_count、输出/resolved_input/时间戳、Run/执行态/checkpoint 中完成与跳过集合、prepared/committed 收据、受控引用及其语义祖先。

分别验证：

1. Compiler 返回的 next_plan 中受保护语义节点正文、绑定身份、有效输入关系必须一致；不只看原始 patch。
2. 下沉后受保护执行节点全部字段、实际前置边以及寻址到该节点的逻辑资源/通信/证据/记忆决定保持一致。新增边可引用既有输出，但若重建的逻辑资源合同变化，则保守拒绝。
3. GraphPatch 必须等于原 derive_graph_patch 对原图/候选图计算的 diff。
4. checkpoint 必须实际存在并属于当前 Run/Graph/version；未知前缀身份、活跃 worker、未解决 node/control review、控制帧/迭代/历史控制审核都拒绝。

Proof 保存保护的 semantic/node keys、涉及节点、原/候选图摘要、原实际依赖摘要、步骤/收据/控制/审核证据摘要、checkpoint 摘要及版本/result=PROVEN。原 Run/Checkpoint 保持可信数据来源，证据摘要不能用于 S03 直接激活。

### 控制图取舍

真实 Runtime 支持 CONDITION 分支选择与 skipped 集、LOOP 的 controlFrames/loopIterations/loopPaths、并行与 Join/consensus 规则、controlReviewDecisions。当前状态未提供足以证明任意历史条件区域的完整不可变选择记录。

更关键的是，现有 semantic patch lowering 只重建 TaskPlan 声明的 verification loops；任意旧 conditional/parallel/join 没有完整保留合同。S02-02 源语义接受本就拒绝控制图。若为本轮强行开放源接受或拼接控制节点，会破坏冻结边界。因此保留 `reject-control-regions-v1`：原/候选图含 control、当前或 checkpoint 存在控制活动/历史，返回结构化 CONTROL_BARRIER_BLOCKED；不存在可完整证明的控制图路径时不清空帧、不忽略控制、不放宽原审核。这一范围缩小是明确限制，不是全控制图 Safe-Cut 的完成声明。

## 确定性及只读并发修复

ACGLowerer 原本生成随机 edgeId 并 touch 时间；图承诺层为候选规范化为原图时间、保留旧边全部字段，为新边按 sourceCommitId/端点/type 派生稳定 ID。没有改写原 Lowerer。不同线程/重启得到同正文；已接受重放读取 ledger，不重新推导。

并发反例先暴露 SQLiteExecutionValueStore 线程绑定的写连接不可跨线程读取（2 failed，2.20s）。仅将 list_node_commits 和 checkpoint.load 的 SELECT 改为独立 mode=ro 连接，无 DDL、写连接共享或执行状态修改；没有重构 Executor/Recovery。随后同 key 并发仍冲突（1 failed/1 passed，4.78s），诊断为随机 edgeId，稳定 ID 修复后同 key ACCEPTED + IDEMPOTENT_REPLAY、不同 key 仅一个 ACCEPTED。Source CAS 与数据库 UNIQUE 为最终防线。

## 自测证据

环境：Python 3.14.5 / Windows 11，默认计时，不请求 1ms。工作目录 apps/agentOS。新增集最终 30 项，真实临时 Workflow/Identity/value/checkpoint SQLite，原 Runtime 与图合同。

覆盖合法 DAG、已完成前缀的独立 pending 扩展、多节点闭合、proof 序列化、重启重放；过期 Mission/Plan/Graph/来源/Scope、执行收据、控制帧、未解决审核、其他 Run、过期接受头；同源跨连接 CAS、INSERT/outbox/commit ack 故障、取消/撤权/authority 缺失/新操作员输入；旧无 index/无 provenance 兼容；没有认证推导的 provider 被拒绝；checkpoint 版本及控制证据。

对全部测试业务 DB 做差异比较，接受本身只有 ledger/outbox 变化。恢复旧 Runtime waiting 转换不采用图候选；普通批准仍完成原来的单节点 v1 图，未执行新节点。源接受 JSON 不修改。

实际运行记录：

| 命令 / 快照 | 结果 |
| --- | --- |
| Graph 新集 + 原 Commit 单元集，初版 | 7 failed / 58 passed，10.94s：控制节点读取方法名及拒绝码优先级修正，无放宽旧测试 |
| Graph 初始 17 项 | 17 passed，14.59s |
| 跨连接反例 | 修复前 2 failed，2.20s；只读连接修复后 1 failed / 1 passed，4.78s；稳定 edgeId 后 2 passed，2.18s |
| 17 项 + 并发 2 项 + S02-02/contracts/architecture | 185 passed，41.78s，中间快照 |
| 补充变化与安全后缀集 | 26 passed，50.32s，中间快照 |
| 新增集 + S02-02 三组 + contracts/architecture | 192 passed，98.04s；195 passed，53.67s，均为后续补 checkpoint/审核验证前快照 |
| 恢复/审核/checkpoint 定向 | 3 passed / 27 deselected，3.30s |
| 最终定向：`python -m pytest -q tests/components/planner/test_graph_revision_commit.py tests/components/planner/test_planning_commit.py tests/components/planner/test_planning_commit_runtime.py tests/components/planner/test_planning_commit_audit.py tests/contracts tests/architecture --tb=short` | **196 passed，57.41s** |
| 扩大：`python -m pytest -q tests/components/planner tests/contracts tests/architecture tests/runtime --tb=short` | **795 passed，432.66s** |
| 最终全量：`python -m pytest -q --tb=short` | **1410 passed，0 failed，1 warning，1307.32s（21:47）**；既有 PyPDF2 弃用警告，Windows 默认计时，未跳过/放宽用例 |

最终源码快照（相对仓库根，按路径排序的本轮 10 个 .py 文件，各行 path+空格+文件字节 SHA256，再 LF 拼接取 SHA256）：`2144d79d3500e01a1e486adffed62517ff6dd760d5ac55ee5c3c8a1d16f974d0`。文档不参与摘要。最终定向/扩大/全量期间不再修改源码；若失败需要修改，重新登记快照并跑最终全量。

一次扩大回归的会话在交互中断后无法回收结束结果，不作为通过证据；随后在同一源码快照重新执行，取得上述 795 项完整结果。最终扩大及全量输出分别保留于系统临时目录 `S02-03-final-broad.log`、`S02-03-final-full.log`，未写入仓库或业务数据库。

## 完整文件差异及下一阶段交接

修改：contracts/planning_commit.py、components/planner/planning_commit.py、support/stores/planning_commit_store.py、runtime/planning_commit.py、runtime/workflow_runtime.py、components/executor/value_store.py、components/recovery/checkpoint.py。

新增：contracts/graph_revision.py、runtime/graph_revision.py、tests/components/planner/test_graph_revision_commit.py，以及本记录。未修改 S02-02 原测试、SemanticRevisionService、ACGLowerer、Topology Compiler、Scheduler、控制引擎、正式 ADR、默认生产装配或业务 DB。

无已知未解决 P1；需要独立验收进一步检验来源投影白名单、推导摘要证书、partial UNIQUE index 与恢复兼容、Safe-Cut 对逻辑资源边界的保守性。P2/限制包括：控制图不支持；跨 DB 仅双检；单进程 Run 生命周期锁；同步有限输入校验仍持全库写锁且无硬延迟；旧源无版本证明不派生；图消费者/前端/业务 DB index 准备未接入。

S03 接收唯一 ledger Record 的 GraphRevisionProposal（源 commit/Run/Graph、next_plan、next_bindings、完整 candidate_graph、派生 patch、proof、版本与摘要）。S03 必须重新验证接受头、正式 GraphVersion/PlanVersion、权限/Basis/scope、收据及控制/审核状态，并执行正式 GraphVersion CAS；历史 PROVEN 与 ACCEPTED 不能直接转为激活/执行。outbox 仍无人消费。

本轮未 Commit、Push、Merge、部署、升级业务数据库或修改正式 ADR；不预先宣称独立验收 ACCEPT。

最终 `git diff --check` 通过；HEAD 仍为入场冻结提交，暂存区为空，差异只有上列 7 个修改文件与 4 个新增文件。最终回归后源码摘要与定向前完全一致。达到本轮最小实施完成标准，具备进入 S02-03 独立代码级验收的条件；控制图完整 Safe-Cut、生产物化与激活均未验收。
