# 知弈 AgentOS · 六大核心能力 · 一页 PPT 文稿

> 用途：答辩 / 路演材料。每个模块一页 PPT，含「页面标题、一句话定位、上屏要点、讲稿文字介绍」四部分。
> 依据：README 核心能力章节、`docs/02-架构设计/05-ACG动态群体智能引擎技术设计.md`、`08-动态并发与统一数据源设计.md`、当前架构图。

---

## 第 1 页 · ACG 动态异构拓扑

**一句话定位**：用一张「有类型」的计算图，把一群 Agent 统一建模成可规划、可并行、可审计的执行真源。

**上屏要点（PPT bullet）**
- 6 类节点 + 7 类边：Step / Agent / Skill / Memory / Evidence / Control 全部入图
- 只有 DEPENDENCY 边参与执行 DAG，其余边交由通信器 / 记忆器 / 审计器分别消费
- 「执行先后」与「数据 / 记忆 / 证据关系」解耦：同一张图既是执行计划，又是血缘图谱
- 就绪集并行调度：关键路径取代线性串行，加速比上界 = 总工作量 / 关键路径
- 存量线性工作流零改动升格为 ACG（`promote_workflow_to_acg`）
- GraphPatch：在 review barrier 上做版本化、不可变的拓扑变更

**讲稿文字介绍**
知弈的核心答案是 ACG——Agentic Computation Graph。我们把 Step、Agent、Skill、Memory、Evidence、Control 建模为 6 类有类型节点，把依赖、通信、控制流、读写和证据支撑建模为 7 类边。关键设计在于：只有 DEPENDENCY 边参与执行 DAG 的构建，其余边由通信器、记忆器、审计器分别消费。这意味着「谁先执行」和「谁的数据、记忆、证据给了谁」是解耦的——同一张图既是可执行的计划，又是可追溯的数据血缘图谱。

执行层面，引擎按依赖关系动态计算就绪集，把无依赖的节点并行调度，将串行执行压缩到关键路径长度；环检测与拓扑排序都是 O(N+E) 的一次性验证。为了兼容存量，我们实现了线性工作流的自动升格，老流程零改动接入新架构。当需求变化或节点失效时，GraphPatch 在 review barrier 上做版本化、不可变的拓扑修补，而不是整链重跑。

---

## 第 2 页 · 低熵通信

**一句话定位**：Agent 之间不再广播自然语言全文，而是按「采购清单」精准投递最小上下文。

**上屏要点（PPT bullet）**
- Communication Broker 是节点间唯一可信中介，杜绝全连接广播与噪声级联
- 按 `input_spec` 精准投递：`from` 定向提取 / `fields` 字段白名单 / 作用域与熵预算
- 结构化传递，不传对话全文；下游只取所需字段
- 实测节省率 99.65%：菱形图 3157 token → 11 token
- Provenance 血缘：前向追溯「结论从何而来」+ 后向定位「数据用在何处」
- 复杂度从 O(ΣSᵢ) 降到 O(F)，避免长程任务 Token 冗余爆炸

**讲稿文字介绍**
传统多 Agent 系统里，Agent 之间全连接广播全文，会带来无关信息扩散、噪声级联和成本失控。知弈的答案是低熵通信：Communication Broker 作为唯一可信中介，节点之间不传自然语言对话，只沿依赖边传结构化数据，并按下游声明的 `input_spec` 这张「数据采购清单」精准投递——定向提取来源、白名单字段、作用域和熵预算逐层收口，最终包装成最小的 ContextPack 下发。

效果是硬指标可衡量的：在菱形图测试中，下游只取 2 个字段、不倾倒上游全文，节省率达到 99.65%（3157 token 压到 11 token）。与此同时，Provenance 账本记录每一次数据的诞生（带校验和）与消费（谁、消费了谁的哪些字段），既支持前向追溯「这个结论从何而来」，也支持后向定位「这个数据被谁用在了哪里」，让低熵不止省 Token，更可审计。

---

## 第 3 页 · 长程记忆与引用式状态

**一句话定位**：六类分库存储 + 引用式输出，让长程任务既不丢记忆，也不被冗余上下文拖垮。

**上屏要点（PPT bullet）**
- 六类独立 Store 分库：Workflow / Checkpoint / Execution Value / Memory / Provenance / Decision
- Run DTO 只返回运行摘要与引用，正文通过 `outputRef` 解引用
- 不把 ContextPack、模型内部状态、工具原文重新塞回长程状态
- Evidence Memory 保存证据与引用，支撑可复核的结论
- Checkpoint CAS 保证中间结论不丢失、恢复后上下文连续

**讲稿文字介绍**
超长程任务最大的敌人是注意力稀释与记忆坍缩：目标漂移、中间结论丢失、恢复后上下文断裂。知弈用「分库 + 引用」双管齐下解决。六类运行数据分别落库——Workflow 存使命与运行、Checkpoint 存中间快照、Execution Value 存正文、Memory 存受控召回的记忆、Provenance 存血缘、Decision 存决策记录，彼此隔离、各司其职。

更关键的是「引用式状态」：Run DTO 只返回运行摘要和引用，正文通过 `outputRef` 按需解引用。这样我们不会把庞大的 ContextPack、模型内部状态或工具原文重新塞回长程状态里，长程上下文的规模不再随步数线性膨胀。配合 Checkpoint 的 CAS 比较与交换机制，中间结论得以稳定保存，即使任务中断再恢复，也能接着原状态继续，而不是从头再来。

---

## 第 4 页 · 自主恢复

**一句话定位**：把「故障 / 需求变化」当作常态输入，注入 → 检查点 → 局部重规划 → 续跑，全程可审计。

**上屏要点（PPT bullet）**
- 故障或需求变化 → guarded runtime 分类与审计 → Checkpoint CAS → Recovery Recipe / contract repair / alternate rebind
- 必要时 GraphPatch 做版本化拓扑修补，保持同一 run_id 与引用所有权继续执行
- FaultInjector 注入 timeout / crash / empty_evidence，验证自愈闭环
- 局部重规划（local_replan）+ recoveryCount 全程留下恢复轨迹
- 动态并发 AdaptiveCallGate：429 退避 2s→4s→8s→60s（指数 + 抖动），加性增、乘性减
- 高风险节点进入 WAITING_REVIEW，审核通过后从原运行恢复，而非任意 checkpoint

**讲稿文字介绍**
静态流水线一旦遇到需求变化或节点失败，往往只能整链重跑。知弈把故障和变化当成常态来处理：guarded runtime 先对异常做分类与审计，再通过 Checkpoint CAS 保存现场，按 Recovery Recipe、合同修复或 alternate rebind 走局部恢复；实在需要改结构时，用 GraphPatch 在 review barrier 上做版本化修补，整个过程保持同一个 run_id 和引用所有权，不破坏溯源链条。

系统内置 FaultInjector 主动注入超时、崩溃、空证据三类故障来验证自愈能力，每次恢复都留下 recoveryCount 和 local_replan 的可审计轨迹。针对真实生产里最头疼的模型限流，AdaptiveCallGate 用指数退避（2 秒起步、×2、60 秒封顶、带抖动）把 429 当作容量信号而非错误，加性增、乘性减地自适应并发窗口，让限流不再放大为整组节点取消。

---

## 第 5 页 · 多模型与外部能力治理

**一句话定位**：模型与工具在冻结的绑定下执行，可协商版本、可健康刷新、可故障切换、可安全换钥。

**上屏要点（PPT bullet）**
- 冻结的 execution binding：能力与版本约束在编译期锁死，杜绝模型漂移
- 异步健康刷新 + 主备 failover + key rotation + 超时重试
- `commitId` 全程稳定，作为外部幂等键透传，重试 / 切换不重复计费
- runtime guards 统一守护模型调用，超时、限流、失败统一处理
- LLM Gateway / Tool Runtime / RAG 三类外部适配器，按协议接入
- 旁路工具（web search / reader）独立预算，耗尽即降级不拖垮主链路

**讲稿文字介绍**
多模型和异构能力是群体智能最容易失控的一环：模型漂移、版本不兼容、故障切换失灵。知弈通过冻结的 execution binding 在编译期就把能力与版本约束锁死，运行时用 AgentProfile binding 做版本协商，异步刷新健康状态，主备 failover 自动切换，密钥轮换不中断服务。每次模型调用的 `commitId` 全程稳定，并作为外部幂等键透传，保证重试和切换不会重复计费。

外部能力通过 LLM Gateway、Tool Runtime、RAG 三类适配器按统一协议接入，runtime guards 在调用外围统一处理超时、限流和失败。旁路工具如 web search、reader 走独立的小预算闸门，预算耗尽或失败时自动降级（标注 webSearchUnavailable）而非让整条主链崩溃——增强能力永远不拖垮核心链路。

---

## 第 6 页 · Milan 可视化闭环

**一句话定位**：从意图到交付物，Run / Graph / Trace / Provenance / Checkpoint / Review / Output 全程可视可复核。

**上屏要点（PPT bullet）**
- Vue 3 Milan 工作台：Run history / Graph / Trace / Provenance / Checkpoint / Review / Output 七类视图
- `/acg` 端点实时暴露拓扑、血缘、恢复轨迹与低熵指标
- 高风险节点 `WAITING_REVIEW`，人工审核 approve 后从原运行恢复
- 感知—规划—执行—反馈完整闭环，Trace 全链路可追溯
- 请求链：Milan → Spring Gateway → FastAPI → WorkflowRuntime

**讲稿文字介绍**
只交付最终文本的 Agent 系统无法解释、复核或追责。Milan 工作台把整个执行过程透明化：Run history 展示运行轨迹，Graph 呈现动态拓扑与并行分支，Trace 记录每个步骤事件，Provenance 展示数据血缘，Checkpoint 允许查看中间快照，Review 支持人工审核节点，Output 通过 outputRef 解引用正文。

对于高风险节点，系统会进入 WAITING_REVIEW 状态，审核人 approve 后从原运行继续，而不是任意回滚历史快照。`/acg` 端点统一暴露拓扑、血缘、恢复轨迹和低熵节省率指标，让技术亮点变成可展示、可量化的证据。整条链路从用户意图出发，经 Milan、Spring Gateway、FastAPI 到达唯一 WorkflowRuntime，形成感知—规划—执行—反馈的完整闭环，也正对应赛题「决策过程与推理轨迹展示」的硬性要求。

---

## 附 · 全篇一句话总纲

> 知弈不是「更多 Agent + 更长 Prompt」的组合，而是一套让群体智能在超长程复杂任务中，长期保持边界、证据与恢复能力的统一运行时——一个内核、一个 Runtime、一个 AgentOS v2 API、一套 Milan 产品外壳、一条可审计执行链。
