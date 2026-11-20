# 中英文图注 / Bilingual figure captions

以下均为原创方法或系统设计示意图，不是实验结果。G 表示执行图版本，S 表示技能版本，M 表示发布清单；下标只在各图内表示相对关系，不表示实际生产版本号。DAG 为有向无环图；CAS 为 compare-and-swap（比较并交换）。

## G1 — 证据驱动的图自进化架构

**中文。** 离线演化从按 Run 去重、保留版本与真实验收结果的轨迹中识别重复失败，形成包含支持证据与反例的诊断假设，再提出绑定基图和内容摘要的受限补丁。候选依次通过快照校验、同任务成对回放及冻结后的独立确认；确认同时检查新任务收益、完整成本与历史能力保持。正式发布服务重新验证身份、报告绑定、兼容性与基版本 CAS，形成可供后续运行固定的版本。新运行的已核验结果进入下一轮证据。研究候选不直接修改活跃运行；任务内恢复属于另一个权限路径。

**English.** Proposed evidence-governed graph evolution. Deduplicated, versioned runs support failure hypotheses and bounded patches tied to a base graph and content digest. Snapshot validation precedes paired replay and fresh confirmation of a frozen candidate, including total cost and retained capabilities. A separate release authority rechecks authorization, evidence bindings, compatibility and the expected base before publication. Future runs pin the approved version and return verified outcomes as evidence. Offline candidates do not mutate active runs; runtime recovery is a separate authority path.

## G2 — 带类型约束的验证器插入补丁

**中文。** (a) 原图 G₀ 将任务产物直接传给后续步骤；(b) 候选 G₁ 在该依赖上插入已注册验证器。只有验证通过的产物引用才能继续，失败则终止或进入预先定义的恢复路径。图中只展示受影响的局部子图，不能据此省略完整图的其他依赖。补丁需记录基版本、目标步骤、算子摘要、输入输出及失败语义。静态无环和类型正确只是必要条件，副作用、并发、成本及真实任务收益仍需回放确认。

**English.** A local validator-insertion patch. (a) G₀ forwards an artifact to downstream work. (b) G₁ introduces a registered validator; only a passing artifact reference may continue, while failure stops or enters an explicit recovery path. The illustration omits unaffected portions of the graph. A patch binds its base, step identifiers, operator digest, I/O contracts and failure behavior. Acyclicity and type checks do not establish side-effect safety or utility; those require controlled replay and confirmation.

## G3 — 三类图的对象与边语义

**中文。** 左：执行依赖图的节点是步骤，边约束运行顺序和数据流。中：候选血缘图的每个节点是完整图版本，边记录生成或融合来源；G₃ 的双父关系只展示可选研究扩展，不表明当前实现支持融合。右：技能关系图的节点是精确技能版本，无向虚线表示可组合，有向边从依赖者指向被依赖技能。技能关系不自动构成任务调度。三个面板中的边不能互换解释。

**English.** Three graph semantics. Left: execution nodes are steps and edges constrain ordering or data flow. Center: each lineage node is an entire graph version; edges record derivation, with multi-parent fusion shown only as an optional extension. Right: nodes are exact skill versions; an undirected dashed edge denotes composability, whereas the dependency edge points from a dependent skill to its prerequisite. Skill relations do not themselves schedule a run. Edge semantics are local to each panel.

## G4 — 图提案状态与保留历史的回滚

**中文。** 正常采纳路径包含草案、静态验证、选择评测、独立确认和正式发布。橙色分支示例分别表示明确未通过、证据不足及基版本/依赖过期；这些分支并非只能从图示状态触发，任一阶段发现不满足条件都应阻止发布。EVALUATED 只表示评测完成，不自动表示结果通过。CONFIRMED 也不能代替真实授权及发布时的 CAS。底部回滚路径将已知良好内容作为新提案，重新验证并生成新版本，保留原运行快照和历史；隐私消费账本不回滚。

**English.** Proposed adoption states and version-preserving rollback. The nominal path covers drafting, static validation, selection evaluation, independent confirmation and publication. The rejection, inconclusive and stale branches are representative rather than exhaustive. EVALUATED means evaluation completed, not that a threshold passed; CONFIRMED is not authorization. Publication rechecks all bindings and the expected base. Rollback republishes known-good content under a new authorized version after compatibility checks, preserving history and pinned runs without reverting privacy consumption.

## S1 — 从执行证据到可复用 Skills

**中文。** 抽象器利用同族成功与失败轨迹提出稳定步骤、可变槽位、适用条件和失效边界，形成 ADD 或 PATCH 候选。候选包通过合同、依赖和程序行为校验，再进行受控比较及独立确认；只有正式发布后才能进入后续任务的可用版本集合。PATCH 生成新的不可变版本而非覆盖旧包。检索使用与经验回流分别见 S2、G1。此路径更新外部技能资产，权重训练属于独立研究方向；来源文档中的内容本身不具有执行授权。

**English.** Evidence-to-skill pipeline. Successful and failed trajectories support abstractions with stable procedures, typed slots, applicability and failure limits. ADD or PATCH proposals undergo package and behavior validation, controlled comparison and independent confirmation before authorized registry publication. A PATCH creates a new immutable version. Retrieval and evidence feedback are detailed in S2 and G1. This pathway evolves external assets; model-weight training is separate, and source material does not confer execution authority.

## S2 — 不可变技能包与运行时检索数据流

**中文。** 左侧定义身份来源、合同边界、步骤程序资源和核验证据；包摘要覆盖文档、脚本、资源及依赖绑定，评测记录作为不可变的关联证明，避免自引用摘要。右侧从任务及运行快照进入混合召回、权限/版本/依赖过滤、重排、预算控制及精确版本绑定，再调用并核验结果。运行快照固定技能目录/索引及允许版本，后续检索不能引入更新版本。各阶段分别记录 retrieved、injected、invoked、result_verified；末端事件框是汇总视图，并不表示所有事件只在执行后记录，也不表示每个召回候选必然完成后续阶段。

**English.** Immutable skill packages and version-filtered runtime retrieval. Package identity, contracts, procedures/resources and evidence remain traceable; the content digest covers executable assets and dependency bindings, while evaluation attestations reference the package without a circular hash. A task and pinned catalog/index feed hybrid retrieval, eligibility filtering, reranking, budget allocation and exact-version binding before invocation and outcome verification. Retrieval cannot introduce versions outside the run snapshot. Retrieved, injected, invoked and result-verified events are distinct and recorded at their respective stages; the event strip summarizes their meanings, not guaranteed progression.

## S3 — 技能更新的受控贡献评估

**中文。** 在固定图 G₀、模型、工具、检索器、其他技能及环境的条件下，对同一批任务比较不注入目标技能、原技能 S₀、候选技能 S₁。预先规定采样、重复、评价器和失败计分，统一资源上限并报告实际上下文与调用成本；不使用无意义填充来伪造“同长度”。选择阶段结束后冻结候选，在按任务族、内容血缘及时间隔离的新鲜确认集上重跑比较，检查质量、误用、成本和历史能力。图示不提供效应量。若图和技能共同变化，应增加 G₀S₀、G₁S₀、G₀S₁、G₁S₁ 四组以分析交互；共同成功奖励不能替代因果归因。

**English.** Controlled evaluation of a skill update. With G₀, model, tools, retriever, other skills and environment fixed, paired tasks compare no target skill, S₀ and S₁ under predeclared sampling, repetitions and scoring. Arms share resource limits, with actual context and invocation costs reported; meaningless padding is not required. After selection, freeze the candidate and repeat the comparisons on fresh confirmatory tasks separated by family, content lineage and time. Assess quality, misuse, total cost and retained abilities. No effect sizes are depicted. Joint graph–skill changes require the four G×S combinations to study interactions; shared reward alone does not establish contribution.

## S4 — Skills 生命周期与独立的召回策略

**中文。** candidate、verified、deprecated、retired 描述技能版本的质量/使用资格状态；进入正式可用集合仍须通过 S1/J1 的真实发布权限。被拒绝或证据不足的研究候选留在探索档案。verified 到 candidate 的虚线表示从旧版派生新候选，不是将已验证对象原地降级。active/dormant 是独立召回维度，不等于质量通过/失败；低频能力需单独保护。退役停止默认发现，但保留历史引用。严重权限撤销可通过独立安全策略立即阻断执行，保留引用不意味着保证历史制品永远可执行。

**English.** Skill lifecycle and orthogonal retrieval policy. Candidate, verified, deprecated and retired describe version status; production eligibility additionally requires authorized publication. Rejected or inconclusive candidates remain in an exploration archive. The dashed return to candidate creates a new version, leaving the verified package immutable. Active/dormant controls retrieval independently of quality, with explicit protection for rare capabilities. Retirement ends default discovery while retaining historical references. An independent security revocation may block execution immediately; retained references do not guarantee perpetual executability.

## J1 — 通过版本清单一致发布图与 Skills

**中文。** 图和技能提案绑定基版本及内容摘要，评测材料绑定候选、基线、数据、评价器和依赖。发布前暂存不可变图制品与技能包，检查其完整性、兼容性及可解析性。发布门同时要求有效评测材料和完整制品；两条输入是 AND 条件。授权服务以预期清单 Mₖ 为 CAS 条件切换到新清单 Mₖ₊₁，并形成可幂等查询的回执；其原子性限定于清单指针和相应事务记录，不要求多个制品存储实现全局事务。新运行只读一次清单并固定版本，已有运行继续使用 Mₖ。回滚按当前基清单重验后生成 Mₖ₊₂。解析/摘要失败则停止启动或明确失败，不降级到隐式 latest；隐私消费账本独立且不回滚。

**English.** Coherent graph–skill publication through an immutable release manifest. Proposals and evaluation attestations bind exact candidate, reference, dataset, evaluator and dependency digests. Validated immutable artifacts are staged before release. The publication gate requires both valid evidence and complete compatible artifacts. An authorized service compares against Mₖ and atomically advances the active pointer to Mₖ₊₁ with a durable, idempotently retrievable receipt. Atomicity concerns the pointer and its transaction records, not a distributed transaction across artifact stores. New runs resolve and pin one manifest; existing runs retain Mₖ. Rollback rechecks the current base and issues Mₖ₊₂. Resolution or digest failures fail closed without implicit latest-version substitution; privacy consumption remains independent.

## 研究来源与归属

图演化的研究背景可引用本地库中的 [GPTSwarm](../../graph_evolution/2402.16823_GPTSwarm.pdf)、[ADAS](../../graph_evolution/2408.08435_ADAS.pdf)、[AFlow](../../graph_evolution/2410.10762_AFlow.pdf)、[GEPA](../../graph_evolution/2507.19457_GEPA.pdf)。技能抽象和复用背景可引用 [Voyager](../../skills_evolution/2305.16291_Voyager.pdf)、[Agent Workflow Memory](../../skills_evolution/2409.07429_Agent-Workflow-Memory.pdf)。本轮沿用既有方法选读与综述，不新增全文精读声明。状态、权限、内容绑定和 manifest 工程方案属于项目综合设计，不将其归因为以上某篇论文的已实现机制。
