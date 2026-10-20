# C2A-2 首次图物化与暂停激活

## 入场与实施前审计

HEAD `dac4217836f3ea468df25f61c8692d38a032704d`；441 个 src/tests Python 文件摘要 `18c378633691a305b15a9036bb6ccafb40987db27a872ede3238fcb82dfcb8f6`，与 C2A-1 ACCEPT 一致。暂存区为空。保留原有 4 个 tracked 修改、来源合同/捕获器/测试和各历史文档。C2A-1 实施记录实际位于仓库根 docs/开发记录，未移动。

| 环节 | 实际权威与复用 | Initial 缺口/边界 |
|---|---|---|
| prepare_run / accept_initial | RuntimePlanningCommitAuthority → PlanningCommitService → SQLite ledger/outbox | 接受后无 Blueprint/Steps；正文已封存，消费不能重调 Planner |
| 来源 | InitialPlanningSourceProvenance + Record.proposalPayload | 当前服务仅作漂移/权限检测，不能补齐输入 |
| 编译 | 唯一 Topology Compiler（含 Binding Solver）、模板/原生 lowering input、ACGLowerer、ACGGraphCompiler | 需新增纯 Initial 重建函数，不引入第二个编译器 |
| 物化 | GraphMaterializationAuthority / graph_materializations | 现有合同仅 revision，需要可区分 Initial 来源、完整候选与绑定；编译在写锁外 |
| 激活 | GraphActivationAuthority / graph_activations / graph_activation_heads | 需支持无源图版本 → v1；不得伪造 v0 |
| 事务 | Journal、Head、Run 与 ledger 位于同一 Workflow SQLite | Head/Run 原子提交可复用；Registry、Identity、代码文件无联合 CAS |
| 执行 | _claim_acg_execution → Head 校验 → Permit Authority | 暂停激活不能授权执行；不调用 Handoff/Permit/Scheduler |

任务清单：封存输入重建；同一 Journal 的 Initial 分支；Head/Run 暂停 CAS；并发/故障/拒绝测试；一次五分钟门禁和最终摘要。

## 实际实现与来源消费

显式宿主入口为 `ExecutionRuntime.materialize_initial_commit(commit_id, idempotency_key=...)`，仍委托原 `GraphMaterializationAuthority.materialize`。旧 `materialize_graph_revision` 显式限定 revision 来源，两个入口不互相冒充。之后调用原 `prepare_graph_activation`、`commit_graph_activation`，不提供自动执行编排，不修改默认 Composition Root 或 HTTP API。

新增 `runtime/initial_graph_compilation.py` 为纯重建函数，不持有 Runtime、Store 或可调用 Agent：

1. 从正式 Ledger 取 Record，重新解析 `sourceProvenance` 和 `proposalPayload`；旧 Initial 无完整来源证明时结构化拒绝。
2. 复用唯一 Topology Compiler 的 existing-plan 校验和内置 CapabilityBindingSolver；不得改写已接受关系。
3. 模板使用封存 Workflow 构造 lowering input；原生使用封存 L1 profile、scoped Catalog、Profile 次序重建独立逻辑 Registry，复用 final-plan rebinding、CognitiveRouter、VariantGenerator 和质量评分。seed/diversity 使用封存值；不解析新意图、不调 LLM、不读取当前资源健康。
4. ACGLowerer 与 ACGGraphCompiler 生成完整 Blueprint、TaskImplementationBinding 和 CompiledACGPackage。逻辑 Agent 的能力还需落在封存 Profile 内。非控制 DAG 之外拒绝；没有合法绑定或缺必要字段时拒绝，不回读当前目录补齐。
5. 当前 Registry、Catalog、Identity、Workflow 的重读只出现在来源围栏，不作为候选内容输入。validationCatalog、Basis、scope、Identity snapshot 和策略摘要保持接受绑定；materialRefs 仍为封存正文。其他 Run 输入不参与编译。

旧 Step 投影会从 Run.input 覆盖 reasoningEffort，并应用 evolutionPolicy。Initial 激活通过同一投影函数的临时空覆盖上下文只投影 Blueprint；真实 Run.input 原样保留，不从未封存正文补齐图或 Step。旧 revision/C1 路径继续原行为。测试证明显式 reasoningEffort 输入保留在 Run 中，但不会越过 Blueprint 改变初始 Step 的规划输入。本轮不签发 Permit，后续执行输入解释仍需在相应权威阶段确认。

除 C2A-1 封存的核心编译器身份外，Initial recipe 另绑定本轮重建、物化、激活、投影及复用的 PlanningEngine 纯方法实现摘要。编译后登记、激活前均重验 recipe；不把当前文件内容替代接受时的核心编译策略。外部代码文件同样不具备跨库原子性。

## 持久化身份与事务

同一 `GraphMaterializationRecord` 以 `sourceKind=initial_plan` 区分来源，增加 `initialContent`（复用 TaskPlan、Bindings、ACGBlueprint）；没有平行 TaskPlan、GraphVersion Store 或 Journal。旧记录默认 graph_revision，继续要求源版本≥1、候选=源+1。Initial 明确 `sourceGraphVersion=null`、`candidateGraphVersion=1`，不存在伪造的 v0。

- Graph ID：Initial Commit + static source fingerprint + materialization policy + recipe 摘要的确定性散列。
- Edge ID：图身份 + 端点 + 边类型的确定性散列。
- Materialization ID：Commit + static source fingerprint + Initial materialization policy；同一 Commit 唯一索引不变。
- Package ID/checksum：既有 Compiler 的完整 Blueprint 哈希和包规范；Journal 完整保存候选、Plan、Bindings、Package 与 checksum。
- 时间戳：首次候选编译的创建/更新时间属于构建元数据。竞争者可以有不同构建时间，唯一持久化赢家封存时间及完整包；同 Key 重放返回该赢家，不重新编译或覆盖时间。新进程按持久化时间重建后完整 content/package 相等，不能把只比较 graph patch 当作完整一致性。
- Activation ID：沿用物化身份/Commit/Package/policy 的稳定派生。

事务外执行 Topology/Binding/Lowerer/GraphCompiler、完整候选与 Run 投影构造。最终 Workflow `BEGIN IMMEDIATE` 内重读接受 head、完整 Record、来源、权限、Run 状态与 recipe 后仅写原物化表。唯一 source/key 索引是跨进程约束，不以 Python 锁替代。

**inactive Journal 是候选版本 1，不是当前 GraphVersion 权威。** 本系统当前不存在需要另行双写的独立 GraphVersion 数据库；正式版本权威是同 Workflow DB 的 `graph_activation_heads`。准备事务只写 ACTIVATION_PREPARED。最终事务再次验证材料、接受与来源，比较完整当前 Run 快照，原子更新 Activation Journal、唯一 Head 和 Run（Blueprint、TaskPlan、Bindings、Package、pending Steps、planningDeferred=false、graphActivation）。Run 写失败/返回 false 均回滚，不能报告激活成功。线性化点是这个 SQLite COMMIT。

`ACTIVATED_PAUSED` 是既有 graphActivation 投影的状态，不新增 WorkflowStatus 枚举。普通 save_run 既不能在 Initial 接受后、Head 建立前伪造 Blueprint/版本/Step，也不能在 Head 建立后回写旧快照。所有执行入口仍由 Head + ISSUED Permit 检查控制。

## 恢复、重放与对抗证据

新增正式测试 `tests/components/planner/test_initial_graph_materialization.py`，使用真实临时 SQLite、正式接受链和 Runtime。

| 切口/反例 | 实际结果与恢复规则 |
|---|---|
| Initial 已接受，尚无物化 | 只读 Ledger，按 Commit ID 消费；不重调 Planner |
| 编译完成但尚未写 Journal | spawn 子进程真实 `os._exit(80)`；父进程确认无 Journal/Head 后从正式接受正文物化 |
| Journal COMMIT 后进程退出 | `os._exit(81)`；新 Runtime 查回同一完整包，重放不编译，再显式准备激活 |
| Activation 已准备、尚无 Head | `os._exit(82)`；重建 Runtime 从同一准备事实提交，不重复生成版本 |
| Head/Run COMMIT 成功、ACK 未返回 | 真实连接 commit 后立即 `os._exit(83)`，不是 Python 异常；重启从正式 Head/Journal 返回 IDEMPOTENT_REPLAY |
| Journal ACK 丢失 | 真 SQLite COMMIT 后抛 OperationalError；返回 STORAGE_UNAVAILABLE，按原 Key 查回唯一事实，禁止再次编译 |
| Head/Run 写入失败 | 真实 SQLite trigger 中止 Head 或 Run 写，Journal 仍 PREPARED、Head 不存在、Run 无图 |
| 投影构造后 Run revision 变化 | 最终完整 Run CAS 拒绝，保留新状态，无 Head |
| 来源/权限/取消/接受头变化 | GraphCompiler 返回前注入变化；最终拒绝，零物化登记 |
| recipe 身份变化 | 编译登记与激活前两个阶段分别拒绝 |
| 同/异 Key 并发 | 真实连接线程竞争；另有两个 spawn 进程在各自完成编译后以 Barrier 汇合，确保真的同时进入最终竞争。恰一个新 Journal；同 Key 返回同身份/checksum，异 Key 拒绝 |
| Activation 竞争/错误 Head | 唯一准备事实与 Head；错误版本 Head 不可被重放覆盖 |
| 历史 Initial / 损坏 Package | 历史可读但缺证明不物化；不一致 checksum 不激活 |
| 原生来源 | 从真实 Native Initial 接受走物化、暂停激活；冻结正文的再次编译完整相等，不用手写 provenance fixture 冒充生产链 |

保留 C2A-1 P2-1：再次 `accept_initial` 在漂移后仍可能 STALE_STRATEGY。本轮不改 PlanningCommitService。测试从 `get_by_idempotency_key('initial-planning:'+run_id)` 找回原 Commit；查回的接受身份/历史物化回执不是当前激活许可，新的 prepare 仍因来源漂移拒绝。新入口接收已知 Commit ID，因此不被重放行为阻断。

## 非执行与兼容范围

Initial 场景在 Handoff、Permit Authority 均已显式装配时，给它们的 prepare/issue 加“被调用即失败”监测；物化/激活均不触发。真实 `_claim_acg_execution` 和 `execute_prepared_run` 都因无 Permit 拒绝。新进程继续同样拒绝。未创建 Attempt、StepExecution、完成状态、Receipt、Checkpoint 或 Artifact；pending WorkflowStep 仅为正式图投影，attempt=0。

物化前后多库逐行 dump（排除唯一允许新增的 Journal 行）相等。C1 的临时回归库会按其既有样例执行原 v1→v2 和恢复/Artifact 链，这是兼容证据，不能解释为 Initial 图获得执行权。

本轮未修改 Permit、Recovery、Handoff、ResourceBinder、NodeRunner、SemanticRevisionService、ACGLowerer/Compiler、API、Artifact 或默认生产装配；只调用既有 SemanticRevisionService 的纯绑定一致性函数，不调用 prepare/commit，不创建 replacement Run。

## 测试与门禁

入场默认 B1 门禁基线已被审计证明过旧。本轮新增 `scripts/freeze_gate_baselines/s03-02c2a1-accepted.json`，完整 441 文件原始字节清单独立复算与 ACCEPT 摘要一致。默认门禁改用该已验收基线；没有把当前新文件加入基线抹去差异。C2A-1 六个源码/测试文件最终均逐字节保持不变。仅共享 freeze_gate 追加当前阶段映射、支持 pytest node ID 路径存在性检查；预算 300 秒、markers 策略、断言与失败语义不变。

选择本轮全部关键测试、旧 Materialization/Activation/Graph Revision 的故障与来源围栏、B2 既有 9 项 Permit 测试、C1 纵向场景及 package/binding/architecture 合同。重叠 node ID 在收集后去重。开发期间只运行直接 node ID；最终正式门禁 `python scripts/freeze_gate.py` 的原始结果和快照在下方补充。本轮不执行全量 pytest，也不重复已有扩大回归。

## 剩余限制与停止边界

- P0/P1：当前针对受支持 Initial 无控制 DAG 路径未发现未解决项；这是实施自测声明，不是独立 ACCEPT。
- P2：跨库联合 CAS 仍不存在。Workflow 的 Record/head/Run 受同一写事务保护；Registry、Identity、代码文件只在最终重读时比较，最后外部读取与 SQLite COMMIT 之间仍有不可联合原子化窗口。不能用历史成功物化回执代替当前激活重验。
- P2：构建时间不是接受时间；并发未登记候选允许不同时间元数据，唯一持久化包可重建。超大 DAG、深接受链、生产并发及锁时长未做性能承诺，接受祖先验证最多 256。
- P2：默认基线现覆盖累积工作区的 C2A-1 ACCEPT 点；C2A-1 仍未提交，后续冻结应保留该分界，不将两阶段混为一次提交或宣称本轮重跑了 C2A-1 全量。
- P3：部分非预期捕获/文件 I/O 错误仍可能以原异常传播；没有执行许可或部分激活可因此产生。未知提交结果必须查原 Key/Head，不能改 Key 重试。
- 旧 Initial 缺正文不会自动升级；不支持控制图或首次 Permit/Handoff；不扩展跨机租约、第三方执行、任意崩溃点恢复。默认应用未接入。

仅可报告 SELF-TESTED，等待独立架构验收；所有修改未暂存、未提交，无 Push/Merge/部署/正式 ADR/业务数据库升级。

## 最终结果：SELF-TESTED

正式门禁仅执行一次，命令（仓库根目录）：

```text
python scripts/freeze_gate.py
```

环境：Python 3.14.5，Windows 11 / build 26100，默认计时配置；未请求 1ms，未修改 deadline、测试断言或 slow marker 语义。

- 开始：2026-10-20 09:18:03.295147 UTC；结束：09:20:41.103623 UTC。
- 总墙钟 **157.808 秒 / 300 秒**（包含收集与启动）；pytest **145.07 秒**。
- **125 passed / 0 failed / 0 skipped / 0 deselected，退出码 0，PASSED**。
- 两项 warning 为既有 Starlette TestClient/httpx 与 Pydantic class Config 弃用提示，没有改依赖。
- 原始门禁报告：`tmp/freeze_gate/20261020T091810Z.json`；原始日志：`tmp/freeze_gate/20261020T091810Z.log`。报告保存完整去重 node ID、实际 pytest 子命令、每项计时、未覆盖/缺失路径为空。`pytest_counts.collected` 因 -q 输出格式为 null，但收集阶段明确保存 125 个 node ID，与最终 125 passed 一致，没有把未知完成数算作通过。

| 最终实际执行范围 | 数量 |
|---|---:|
| 本轮 Initial 物化/暂停/并发/进程故障/来源/历史兼容 | 29 |
| 既有 Execution Permit 门禁 | 9 |
| 既有 Activation 关键反例 | 10 |
| 既有 Materialization 关键反例 | 20 |
| Graph Revision 完成前缀和 checkpoint/control 证据 | 3 |
| CompiledACGPackage 合同 | 30 |
| Binding Authority 合同 | 6 |
| Architecture 门禁 | 15 |
| C1 纵向恢复与交付 | 3 |
| 合计 | 125 |

本轮未执行完整 Planner/Runtime 扩大集、全量 pytest、大图性能、多机器竞争或外部供应商调用。不能据此声称全量无回归。开发期直接 node ID 反馈包含原生夹具能力不足的拒绝（补齐真实注册能力后再正式接受），以及接入原 existing-plan gate 时不支持 USER_DECLARED origin 的校验失败（改用既有固定 PLAN_PATCH origin，没有放宽 Topology 校验）。最终门禁已覆盖修改后的全部本轮关键反例。

### 最终快照与范围

443 个 src/tests Python 文件聚合 SHA-256：

`d08de700d22e375ec480ab9b6bb8978cbb96bc6079874856e71fb43422ebe0c9`

算法：每个文件按原始字节 SHA-256；以相对仓库根的 POSIX 路径排序，组成 `路径 空格 文件SHA`，用单个 `\n` 连接、无末尾换行，再对其 UTF-8 字节 SHA-256。完整清单保存 `tmp/c2a2-final-snapshot.json`。门禁结束与最终复算一致。

- API 原始字节 SHA：`b78ffdd8d0b1c004f9befdd63c7372070cf9a733c244f86591328897791ccc21`（未变）。
- freeze_gate 原始字节 SHA：`4ee8db0322cf289e30a06ab429cf9dc8072a07b7166c0af5cec523d827703a09`。
- C2A-1 基线 manifest 文件自身 SHA：`1848fd570613c84fd0bf2afe9ca5312a61d642a0e6d013b7412a2e80a1b8bd97`；其内 441 文件清单聚合仍为 `18c378633691a305b15a9036bb6ccafb40987db27a872ede3238fcb82dfcb8f6`。

相对 C2A-1 ACCEPT 本轮修改六个既有源码文件：`contracts/graph_materialization.py`、`contracts/graph_activation.py`、`runtime/graph_materialization.py`、`runtime/graph_activation.py`、`runtime/workflow_runtime.py`、`support/stores/graph_activation_store.py`；新增纯重建模块与 29 项测试。另修改根门禁脚本、新增已验收基线清单和本实施记录。其余 C2A-1 累积变更未合并、未回滚、未提交。

最终 HEAD 仍为入场 Commit，分支 master，暂存区为空。`git diff --check` 退出码 0；只有既有 LF/CRLF 提示，未更改行尾以凑摘要。未触碰 README、EX-00、架构图片、正式 ADR、默认应用装配或业务数据库。

具备提交独立验收的自测证据；**不自行给出 ACCEPT，不代表 Initial 可以执行**。
