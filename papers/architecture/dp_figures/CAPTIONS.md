# 双语图注与符号

本组图是 Kinlin 差分隐私发布的原创目标设计。数学基础来自下列参考文献，工程事务、状态名称及恢复协议是本项目设计建议，不归因于这些论文的既有实现。所有图共用以下前提。

**保护域与观察者。** 邻接为同一声明允许域内的完整 prompt replacement，保持声明为公开的信息相同；不自动等同于保护用户参与、所有历史对话、训练样本或 RAG 记录。随机化发生在可信客户端内，云端可以观察批准的随机载荷及协议明确允许的 transcript。本地原始输入、原始激活、私有 KV 和噪声随机性不得额外出站。

**会计原型。** 第一版冻结公开的最大发布次数 T、裁剪阈值与噪声调度、阶数集合 A ⊂ (1,∞)、δ*、总预算及同一保护范围。每步在给定过去 transcript 条件下满足同一邻接的 RDP 上界。参数或停止规则若依赖未发布私有状态，必须重新分析；这些图不声称解决任意自适应参数的 privacy filter 问题。

**协议闭合。** 公开形状、固定元数据和调度必须对所比较的相邻输入一致，或由已发布 DP 结果的后处理产生；其他可观测通道需要单独机制或明确排除在威胁模型之外。不能只在文档中把实际依赖私有输入的字段“命名为公开”来消除泄漏。

## 图 1 / Figure 1

**中文：本地隐私发布架构。** 私有输入与本地前导网络的私有 KV 留在可信本机。向云端后段发布的激活必须经过发布门；发布门依据不可变隐私合同执行裁剪、随机化和唯一载荷绑定，并在预算持久预留及载荷持久化后开放发送。云端返回步骤结果与提交回执，本地核验后进入下一步；下一次读取私有状态形成的新激活仍需重新经过发布门。紫色模块表示持久预算账本与载荷发件箱，虚线表示控制或返回通路。该图描述目标边界，不构成对尚未实现协议的 DP 保证。[R1, R2]

**English: Local privacy release architecture.** Private inputs and the prefix model's private KV remain within the trusted client. Every activation sent to the remote suffix passes through a release gate governed by an immutable privacy profile. The gate clips and randomizes the activation, binds one payload to its release identifier, and permits transmission only after durable budget reservation and payload preparation. The client verifies the returned step result and commit receipt before continuing. A subsequent activation that reads private state requires another accounted release. Purple modules denote durable state; dashed links denote control or response paths. This is a target architecture under the stated assumptions, rather than a privacy claim for an implemented protocol. [R1, R2]

## 图 2 / Figure 2

**中文：先记账、后发送的发布数据流。** 对新发布依次完成合同校验、原子去重与预算预留、一次随机化、唯一字节持久化及 MAYBE_SENT 预写，再经认证加密通道发送。回执核验后记录 ACKED，不重复收取已预留费用。重复标识须校验原绑定并进入恢复流程，不重新预留或采样。图中步骤 2 的前瞻检查和账户更新属于同一可串行化事务；步骤 6 以后超时不视为从未发送，按图 3、5 处理。

**English: Write-ahead release dataflow.** A new release proceeds through profile validation, atomic deduplication and budget reservation, one randomization, durable preparation of the exact bytes, and a write-ahead MAYBE_SENT marker before authenticated encrypted transmission. A verified receipt transitions the release to ACKED without a second charge. Duplicate identifiers must match the original binding and enter recovery rather than reserve or sample again. The prospective check and account update in step 2 share one serializable transaction. A timeout after transmission does not establish that no disclosure occurred; recovery follows Figures 3 and 5.

## 图 3 / Figure 3

**中文：持久隐私发布状态机。** 正常路径为 NEW → RESERVED → PREPARED → MAYBE_SENT → ACKED。账户在进入 RESERVED 时计入上界，进入 MAYBE_SENT 前禁止网络发送。恢复只允许在核查图 5 的条件后使用原载荷；同一发布标识不得绑定新的随机样本。不可恢复预留、载荷丢失或无法安全确认会话时进入 SEALED_CHARGED，停止本地进一步发送并保留费用。该状态不证明远端从未执行，也不能撤销已经在途的请求。箭头展示关键路径，恢复中的条件查询在图 5 展开。

**English: Persistent release state machine.** The normal path is NEW → RESERVED → PREPARED → MAYBE_SENT → ACKED. The account includes the conservative cost upon reservation, and network transmission is forbidden before MAYBE_SENT. Recovery may reuse only the original payload, subject to the conditions in Figure 5; a release identifier never authorizes a new random sample. An unrecoverable reservation, missing payload, or unsafe session state enters SEALED_CHARGED, preventing further local sends while retaining the charge. This terminal marker neither proves that the remote step never executed nor cancels work already in flight. Recovery queries are expanded in Figure 5.

## 图 4 / Figure 4

**中文：Gaussian 发布与前瞻组合会计。** (a) 将一次发布的完整激活展平为 h(x) ∈ ℝᵈ，进行全局 L2 裁剪得到 h̄(x)，并发布 Y = h̄(x) + Z，其中 Z ∼ N(0,s²I)。完整输入替换邻接下，‖h̄(x)‖₂ ≤ C 给出保守敏感度 Δ₂ ≤ 2C。(b) 在固定公开费用调度下，对每个 α ∈ A，本次条件 RDP 费用为 cₜ(α) = αΔₜ²/(2sₜ²)。包含全部预留的账户 R 与本次费用分别进入转换，计算 ε_pros = min_{α∈A}[R(α)+cₜ(α)+ln(1/δ*)/(α−1)]；通过总预算检查后原子写入 R ← R+cₜ，否则拒绝发送。图示为实数 Gaussian 的理论上界，有限精度实现需另行验证；没有使用子采样放大。[R1–R3]

**English: Gaussian release and prospective composition.** (a) One complete publication is flattened into h(x) ∈ ℝᵈ, globally L2-clipped to h̄(x), and released as Y = h̄(x) + Z with Z ∼ N(0,s²I). Under whole-prompt replacement, ‖h̄(x)‖₂ ≤ C yields the conservative sensitivity bound Δ₂ ≤ 2C. (b) Under a fixed public cost schedule, the conditional RDP cost at order α ∈ A is cₜ(α) = αΔₜ²/(2sₜ²). The account R, including all reservations, and the new cost enter the prospective conversion separately: ε_pros = min_{α∈A}[R(α)+cₜ(α)+ln(1/δ*)/(α−1)]. The check and update R ← R+cₜ are atomic; an over-budget release is rejected. The equations describe the real-valued Gaussian mechanism; finite-precision implementations require separate validation. No subsampling amplification is applied. [R1–R3]

## 图 5 / Figure 5

**中文：不重采样的丢失回执恢复时序。** 本地先预留、采样并固化载荷，再写可能出站标记；云端在同一会话串行控制下将 KV 推进、采样 token 与回执作为一个逻辑步骤提交。回执丢失后查询权威状态：COMMITTED 复用原回执并使本地步骤最多推进一次；NOT_COMMITTED 仅允许同一有效会话中重发完全相同的载荷；UNKNOWN 或会话失效停止并保留消费。NOT_COMMITTED 必须排除在途执行，普通 lookup 为空不满足该条件。查询与重发之间仍须使用会话 epoch/步骤去重及 fencing，防止旧执行者晚到提交。隐私账本事务与云端步骤事务彼此独立。

**English: Lost-receipt recovery without resampling.** The client reserves the cost, samples and persists one payload, and writes the possible-egress marker before transmission. Under per-session serialization, the cloud commits the KV update, sampled token, and receipt as one logical step. After a lost reply, the client queries authoritative state: COMMITTED reuses the original receipt and advances the local step at most once; NOT_COMMITTED permits only an identical-payload retry in the same valid session; UNKNOWN or an invalid session stops further sends while retaining the charge. NOT_COMMITTED must exclude in-flight execution; an empty lookup is insufficient. Session epochs, step deduplication, and fencing remain necessary across query and retry to prevent a stale executor from committing later. The privacy ledger and the remote step use distinct transactions.

## 图 6 / Figure 6

**中文：协议可观测范围与发布约束。** 观察者可见数值、形状/位置元数据以及停止、异常与时序等交互记录。激活数值经过完整向量随机化；长度、mask 和 offset 必须满足批准的公开形状、padding 与元数据白名单；行为通道须执行批准规则并纳入分析，或明确收窄保护范围。拒绝与失败本身也可能成为信号，因此仅“阻止原始字段出站”不能证明完整 transcript 的隐私。未经批准不得降级发送原文。[R1, R4]

**English: Protocol observability and enforcement.** The observer sees numerical values, shape and position metadata, and interaction behavior such as stopping, errors, and timing. Activation values pass through complete-vector randomization. Lengths, masks, and offsets must follow the approved public shape, padding, and metadata allowlist. Behavioral channels require enforced rules and analysis, or an explicit restriction of the claimed observation scope. Rejection and failure can themselves reveal information; blocking raw fields alone does not establish privacy for the full transcript. Raw-text fallback is prohibited. [R1, R4]

## 符号与术语

| 符号/状态 | 精确定义 |
|---|---|
| x | 声明允许域内的私有 prompt；相邻比较保持公开上下文不变 |
| h(x), h̄(x) | 一次完整发布向量，以及该向量的全局裁剪结果 |
| C, Δₜ | 裁剪阈值与所选邻接下的第 t 次敏感度上界 |
| sₜ | 每坐标 Gaussian 标准差；不是未说明标度的 noise multiplier |
| A, α | 固定有限 RDP 阶数集合及其中一个大于 1 的阶数 |
| R(α), cₜ(α) | 账户累计保守 RDP 上界与本次待预留费用；R 包含全部持久预留 |
| δ*, ε_pros | 预先选定的转换参数与加入本次费用后的 ε 上界 |
| releaseId | 不泄露输入内容的发布标识，必须绑定账户、scope、profile、模型/协议版本、会话 epoch、步骤和唯一载荷 |
| receipt | 经认证且绑定请求、会话 epoch、步骤及载荷摘要的提交结果；不是隐私证明 |
| MAYBE_SENT | 本地已持久记录“允许且可能已经发送”；不是送达确认 |
| SEALED_CHARGED | 本地停止进一步发送并保留费用，不表示远端回滚或未执行 |

## 文献与设计来源

- **R1** Dwork, C. and Roth, A. *The Algorithmic Foundations of Differential Privacy* (2014)，§2–3 与 Gaussian 附录。[本地全文](../../differential_privacy/2014_Dwork-Roth_Algorithmic-Foundations-DP.pdf)，[出版页面](https://www.cis.upenn.edu/~aaroth/privacybook.html)。用于邻接、机制、后处理与组合背景。
- **R2** Mironov, I. *Rényi Differential Privacy* (2017)，采用本地收录的 arXiv v3。[本地全文](../../differential_privacy/1702.07476_Renyi-DP.pdf)，[原文](https://arxiv.org/abs/1702.07476v3)。用于 Gaussian RDP、顺序组合和基础转换。
- **R3** Balle, B. and Wang, Y.-X. *Improving the Gaussian Mechanism for Differential Privacy: Analytical Calibration and Optimal Denoising* (2018)，arXiv v2。[本地全文](../../differential_privacy/1805.06530_Analytic-Gaussian.pdf)，[原文](https://arxiv.org/abs/1805.06530v2)。用于校准边界与机制选择背景；图 4 没有声称实现其校准算法。
- **R4** Rogers, R. et al. *Privacy Odometers and Filters: Pay-as-you-Go Composition*，本地收录 arXiv v3。[本地全文](../../differential_privacy/1605.08294_Privacy-Odometers-Filters.pdf)，[原文](https://arxiv.org/abs/1605.08294v3)。用于说明自适应参数/停止规则需要额外理论，不用于声称本设计已实现 filter。

项目依据：[差分隐私综述](../../differential_privacy/SUMMARY.md)、[三个模块架构设计](../ARCHITECTURE_DESIGN.md)。本组图没有复用论文图片，也没有生成实验测量数据。
