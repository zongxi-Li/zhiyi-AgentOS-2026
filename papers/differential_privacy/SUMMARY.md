# 从“给激活加噪”到可核查的隐私发布：差分隐私文献与 Kinlin 实现路线

整理日期：2026-11-18。本主题收录 17 篇论文和 1 部基础专著。书目、版本、来源与阅读深度见 [索引](README.md)。这是主题检索与重点方法选读，没有运行论文实验，也没有为项目建立新的隐私保证。本文把原文结论、项目现状和设计建议分别表述。

## 1. 研究结论与适用边界

Kinlin 最需要的不是先挑一种噪声分布，而是明确：保护谁的一条什么信息，谁能看到什么，一段交互总共释放了多少信息。DP-SGD 保护训练样本的参与影响；推理时向不可信云端发送激活，则需要针对推理输入及完整交互记录定义机制。两者保护的对象不同。

文献给出三条可以并行研究、不能混报预算的路线：标准邻接定义下的裁剪与 Gaussian 发布；Split-and-Denoise 一类距离相关的 metric privacy；DEL 一类带随机量化、降维和效用补偿的专用机制。建议项目首先完成可解释、可审计的 Gaussian 基线，再比较后两者。较低的反演成功率是有价值的实验结果，但不能替代定义、敏感度和组合分析。

当前 `components.safe` 明确只提供 `split-baseline-v1`，`PrivacyProfile.guarantee` 为 `none`，`PrivacyReleaseService.release()` 抛出 `PRIVACY_UNAVAILABLE`。这与已经实现真实模型拆分、KV 会话和认证 HTTPS 并不矛盾：运行链路和隐私发布是两个独立验收目标。

## 2. 文献地图：每一组在解决什么问题

| 组别 | 代表材料 | 核心作用 | 对项目的直接意义 |
|---|---|---|---|
| 定义与后处理 | [Dwork–Roth 专著](2014_Dwork-Roth_Algorithmic-Foundations-DP.pdf)，§2、§3、附录 A | 邻接、DP、组合、Gaussian | 写清 profile 的数学含义 |
| 训练保护 | [DP-SGD](1607.00133_DP-SGD.pdf)、[DP 语言模型 scaling laws](2501.18914_DP-LM-Scaling-Laws.pdf)、[分层 IR 风险训练](2602.22611_DP-Training-Intermediate-Representations.pdf) | 梯度裁剪、随机训练及训练会计 | 未来用私有轨迹训练模型时另建预算；不能替代激活发布 |
| 组合会计 | [RDP](1702.07476_Renyi-DP.pdf)、[采样 Gaussian](1908.10530_Sampled-Gaussian-RDP.pdf)、[子采样 RDP](1808.00087_Subsampled-RDP-Accountant.pdf)、[PRV 数值组合](2106.02848_Numerical-Composition.pdf) | 追踪多次发布，减少粗糙组合损失 | 逐 token 与跨会话账本的理论基础 |
| 校准与在线预算 | [Analytic Gaussian](1805.06530_Analytic-Gaussian.pdf)、[Odometers/Filters](1605.08294_Privacy-Odometers-Filters.pdf) | 更精确校准；区分跟踪与预算停止规则 | 不把动态调整预算当普通固定参数组合 |
| 推理输入保护 | [SnD](2310.09130_Split-and-Denoise.pdf)、[DEL](2602.11513_DP-Split-Stochastic-Quantization.pdf)、[字符级 prompt 扰动](2603.26032_Character-Level-DP-Prompts.pdf) | 在云端看到输入之前随机化 | 需要说明 token、字符、序列及会话之间的保证转换 |
| 数据库与标签保护 | [LDP-ICL](2405.04032_Local-DP-ICL.pdf)、[DP-RAG](2602.14374_DP-RAG.pdf) | 分别涉及敏感标签与检索语料 | Planner 的用户输入、经验库、检索库不是同一种隐私单位 |
| 反例与评估 | [FSHA 对 DP split learning 的攻击](2201.04018_Feature-Space-Hijacking-DP.pdf)、[metric DP 校准](2503.13872_Metric-DP-Calibration.pdf)、[Guarding the Middle](2602.17614_Guarding-the-Middle.pdf) | 检查保护对象错配、重建风险与中间表示 | 不因使用某个 DP optimizer 就宣称所有通信安全 |

本表中 SnD、DEL、Gaussian/RDP 和数值组合进行了方法选读；其余若只审查摘要，在索引中明确标注。2026 年预印本以清单记录的 arXiv 版本为准。

## 3. 首先定义隐私单位和观察者

标准 `(ε, δ)`-DP 要求，对所声明的任意相邻输入 `x ~ x'` 和可观测事件 `S`：

\[
\Pr[M(x)\in S]\le e^{\varepsilon}\Pr[M(x')\in S]+\delta.
\]

概率来自机制的随机性。ε 约束相邻世界之间的可区分程度；δ 是近似保证中的加性松弛，不能简单解释成某次请求“有 δ 概率泄密”。DP 也不是加密：它允许输出具有用途，限制的是所声明邻接关系下额外信息的变化。

应为 Kinlin 至少区分以下候选定义，而不是同时声称全部成立：

- **token replacement**：固定长度中替换一个 token。可以研究局部变化，但不自动保护整段病历或整位用户。
- **prompt replacement**：固定允许域和长度协议下替换一条完整输入。范围更强，通常付出更大效用代价。
- **user/session 邻接**：一名用户的多轮数据整体变化。需要给贡献次数上界、跨会话预算和停止策略。
- **数据库 record 邻接**：保护 RAG 或训练语料中一条记录的参与。与提问者 prompt 的隐私不同。

云端是不可信观察者时，随机化必须在可信本地完成。把原始激活先交给云端再由云端加噪，只能支持另一个信任模型，不能保护输入免受该云端观察。

声明还应包含：客户端/服务器是否诚实遵循协议，攻击者是否知道前段权重，有无辅助数据、重复查询、公开 tokenizer 和模型。对主动改变模型或协议的服务器，必须额外验证本地前段制品、入站反馈和执行边界；被动服务器下的证明不能直接覆盖任意主动攻击。

## 4. 标准 Gaussian 基线：裁剪、校准和组合

### 4.1 明确裁剪的是哪个向量

设一次允许发布的激活整体展平成 `h(x) ∈ R^d`，全局 L2 裁剪为：

\[
\bar h(x)=h(x)\min\left(1,\frac{C}{\|h(x)\|_2}\right).
\]

对任意两条 replacement 输入，三角不等式给出 `Δ₂ ≤ 2C`。这是一个保守但清楚的上界；若要用 `C` 而不是 `2C`，必须证明与所选邻接和查询形式相符，例如特定 add/remove 聚合，不能凭惯例更换。逐 token 单独裁剪后整段一起发布，也不能继续把整段敏感度写成单 token 的 `2C`。

项目 [clipping.py](../../apps/agentOS/src/components/safe/infrastructure/privacy/clipping.py) 已实现全局 L2 裁剪；它本身是确定性有界映射，不是 DP 机制。

在有界向量上发布：

\[
Y=\bar h(x)+Z,\qquad Z\sim\mathcal N(0,s^2I_d).
\]

`s` 表示每坐标标准差，区别于代码中常见的 noise multiplier。若使用 multiplier `z`，应明确 `s = zΔ₂` 还是 `s = zC`，两者在 replacement 情形下相差一倍。经典充分界通常写成 `s ≥ Δ₂ sqrt(2 ln(1.25/δ))/ε`，其常用定理有 `0 < ε < 1` 等条件；不应将它无条件扩展到任意 ε。

[Analytic Gaussian](1805.06530_Analytic-Gaussian.pdf) §3–4 直接使用 Gaussian CDF 校准，在给定全局敏感度、ε、δ 下求可行噪声。它改进的是校准精度，不会消除邻接定义和多次发布成本。高维情况下噪声 L2 尺度约为 `s√d`，所以“每坐标只有一点噪声”仍可能严重损坏长序列激活。

### 4.2 逐 token 不是免费后处理

对标准 Gaussian 机制，在阶数 `α > 1` 下可用：

\[
\rho_t(\alpha)=\frac{\alpha\Delta_t^2}{2s_t^2},\qquad
\rho_{1:T}(\alpha)\le\sum_{t=1}^{T}\rho_t(\alpha).
\]

再用一个有效的基础转换得到：

\[
\varepsilon(\delta)\le
\inf_{\alpha>1}\left[\rho_{1:T}(\alpha)+\frac{\ln(1/\delta)}{\alpha-1}\right].
\]

这里要求每一步在给定过去公开 transcript 的条件下，对同一声明的邻接关系成立；不能只测一批激活的平均距离。自回归 decode 的新激活可能继续依赖原始私有 prompt 或本地 KV，因此通常是新查询，而非前一次 noisy 激活的纯后处理。prefill、每次 decode、重采样以及多会话都需纳入上界。

采样放大文献适用于满足假设的随机子采样机制。每一步都发送当前用户的激活，没有“只抽中了少部分用户”的过程，不能照搬 DP-SGD 的 sampling rate 来降低预算。

最初可以冻结最大 T、C、噪声和 α 网格，以保守 RDP 会计运行。PRV 可用于适用机制的更紧数值分析，但应记录离散化、截断与误差容限。若根据私有中间状态动态改预算或停止，需结合 privacy filter 等理论；普通“余额减一”不自动给出自适应参数保证。

## 5. SnD：本地去噪的边界与 metric privacy

[Split-and-Denoise](2310.09130_Split-and-Denoise.pdf) 重点是 Embedding-as-a-Service 和下游语义任务：客户端保留 embedding 层，在发送前扰动；云端运行剩余模型，返回扰动后的输出表示；本地去噪器结合本地原输入和噪声相关信息恢复效用。它没有要求修改预训练 LLM 权重，但去噪器本身仍有训练/部署成本。

其核心保证使用距离相关的 `η dχ` privacy，采用 L2 距离及球对称 Laplace 型扰动。距离越大允许的分布差异越大，因此数值 η 不能直接与标准整 prompt replacement 的 ε 比大小。若要转换，必须指定有界输入域及最大距离，或保留原有 metric 声明。

两点对项目尤其关键：

1. 原输入和噪声信息留在本地。把这两者发给云端来“帮忙去噪”，会改变甚至破坏机制的观察边界。
2. 本地去噪能改善本地任务输出；若再把依赖原私有输入的去噪结果发出，这次发布需另行分析。只有不重新读取私有输入、仅处理已经发布结果的映射才能直接使用后处理性质。

SnD 适合做低成本 EaaS 对照，不宜直接推断它解决了任意长度开放式自回归生成。项目应先挑固定输入长度、固定输出任务，再扩展会话。

## 6. DEL：随机量化同时处理通信与效用

[DEL](2602.11513_DP-Split-Stochastic-Quantization.pdf) 的组合是本地 embedding、降维编码器、随机量化、云端解码和 soft prompt 补偿。相比直接传高维浮点 embedding，它同时优化通信量和扰动后的可用性。

其 n-bit 二项随机量化可以概括为：对满足坐标界 `v ∈ [-c,c]` 的输入，取 `A ≥ c`、`u = 2^n−1`，令

\[
p=(A+v)/(2A),\quad K\sim\operatorname{Binomial}(u,p),\quad
Q(v)=A(2K-u)/u.
\]

这是一种有特定分布的随机机制，不能用普通最近邻取整替代后沿用证明。论文采用 f-DP/GDP 分析；有限维结果含误差项 γ，不应把所有配置称作“精确等价 Gaussian 机制”。文中坐标界 `c=C/√d` 也不能仅从 `\|v\|₂ ≤ C` 推出：后者只给单坐标不超过 C，需要实际执行额外坐标约束或满足相应机制假设。

在效用补偿阶段，DEL 冻结 LLM 与编码/解码模块，训练云端 soft prompt 适配扰动分布。这一策略提示：与其减小噪声直到保护失效，不如让下游适应机制。但迁移时应分别核查压缩模块训练、soft prompt 数据来源，以及额外训练是否读取私有数据。推理 DP 不自动覆盖训练数据。

建议复现顺序为浮点无扰动基线 → 压缩不加隐私噪声 → 随机量化 → soft prompt。分别报告收益，防止把压缩、训练适配和隐私机制的贡献混在一起。逐 token 保证还需转换到明确的完整序列与交互成本。

## 7. 反例告诉我们：保护对象必须对齐

[FSHA against DP Split Learning](2201.04018_Feature-Space-Hijacking-DP.pdf) 研究恶意服务器操纵 split learning，并使用客户端 DP optimizer 的场景。其攻击结果说明：训练参数层面的 DP 机制，不能自动保护另行泄露的 smashed data。不能把它解读成“正确校准的激活 DP 在任意 ε 下都没有意义”，因为保护通道和邻接对象本来就不同。

[Metric DP Calibration](2503.13872_Metric-DP-Calibration.pdf) 比较不同扰动体系下的经验校准，提示成员推断与重建攻击的敏感性不同。对 Kinlin，攻击曲线应与正式会计并列报告：前者测选定威胁条件下的泄漏，后者界定所有允许相邻输入的保证。攻击失败不是证明，攻击成功也应说明是否超出所声明的保护范围。

DP-RAG、LDP-ICL、字符级机制可作为后续支线：先明确语料 record、标签、字符还是 prompt 为隐私单位，再考虑接入。不要把论文标题里的 DP 当作覆盖整个 Agent 工作流的许可证。

## 8. 项目差距与发布事务建议

代码核查范围：[privacy 合同](../../apps/agentOS/src/components/safe/contracts/privacy.py)、[发布服务](../../apps/agentOS/src/components/safe/application/privacy.py)、[预算规则](../../apps/agentOS/src/components/safe/domain/budget.py)、[组件说明](../../apps/agentOS/src/components/safe/README.md)。这些文件包含后续实现 TODO，不能将设计目标写成既成能力。

建议把一次发布实现为持久事务，下面是设计而非本轮新增代码：

```text
校验 immutable profile 和完整发布范围
→ 按 owner/profile/window 原子预留预算
→ 本地产生随机扰动，固定将要发送的 payload 字节
→ 持久绑定 release_id、机制版本、会计参数及 payload 摘要
→ 经认证通道发送
→ 保守记录已出站或可能出站的成本
```

幂等重试只重发同一份 noisy payload，不能每次重新采噪再复用同一个收据。服务端或网络若已观察前一次 payload，新样本就是新增信息；未知是否出站应保守计费，不因超时自动退款。只有能证明未发布且未被观察的预留，才能按明确协议撤销。

账本需跨重启、跨会话保留。owner 不能由请求方随意换值绕过聚合；更换 profile 也不能重置同一保护主体的累计成本。nonce 防重放、认证和预算消费各自解决不同问题，持久 nonce 不等于持久隐私账本。日志保留审计摘要，避免写入原文、噪声种子或原始激活；持久 payload 也需受控存储及生命周期管理。

遗留 [federatedlearning.py](../../apps/agent/app/services/federatedlearning.py) 中按 `1/epsilon` 缩放噪声的做法，没有为当前激活查询给出敏感度、δ 和多次发布会计；按参数块裁剪也不等价于当前全激活裁剪。本轮只指出复用边界，没有改动该文件。

## 9. 完整 transcript 与评估方案

对手看到的不只是一个浮点数组。张量形状、attention mask、长度、batch、切分层、生成停止、包数量、重试和时序都可能依赖私有输入。若声明固定长度的内容隐私，可先用公开上限、padding 和明确的元数据披露范围建立小而完整的协议；若要保护长度或停止，则需额外机制。不能只扰动 tensor 值却对整段会话做未经分析的强声明。

建议采用以下验收矩阵：

| 目标 | 必要实验或检查 | 解释范围 |
|---|---|---|
| 数学正确 | 邻接、Δ、机制条件、会计参数版本及可复核示例 | 检查实现是否符合选定保证 |
| 发布正确 | 并发、崩溃恢复、重试、未知出站、跨 session 余额 | 不漏计已经释放的信息 |
| 任务效用 | EM/任务完成率、语义质量、长短输入分桶 | 不能只报告 embedding 相似度 |
| 反演风险 | ActInv/学习型攻击、实体恢复、token 恢复；公开前段与辅助数据设定 | 仅为所测攻击条件的经验结果 |
| 系统成本 | 首 token、TPOT、上下行字节、内存、账本写入耗时 | 分开报告机制与拆分开销 |
| 多轮行为 | 固定 T 与最大 T、跨任务、取消与重试 | 单次预算不冒充整会话预算 |

可执行路线：第一阶段冻结无保证基线及测量；第二阶段在独立实验中完成 fixed-shape Gaussian 和 RDP；第三阶段接入持久发布事务及故障测试；第四阶段在同样威胁和任务上比较 SnD/DEL；第五阶段才将通过审查的 profile 暴露给产品。是否开展模型训练由效用曲线决定，不应一开始就同时改模型、协议、会计和 Planner。

## 10. 与 Planner 和两种前导模型的组合

Intent Analyzer 若在本地先提取必要任务信息，可能减少外发字段，但“语义摘要”仍然可能包含姓名、病情与约束，不自动构成 DP。经验库也可能积累用户内容，应与公开规则模板分开，遵循来源授权、保留期和检索范围；若要给经验库记录提供 DP，需要另建 record-level 机制。

本地前导网络提供随机化的可信位置，Planner 提供任务和预算需求，Runtime 执行正式发布策略。Planner 可以建议高质量或低延迟模式，但不能临时改邻接、把余额清零或替用户解除隐私 profile。三者接口应传递明确的 profile 引用和成本预测，不传递未经证实的“绝对安全”标签。

配套阅读：[端云拆分前导网络](../leading_model/SUMMARY.md)、[意图理解前导模型](../intent_model/SUMMARY.md)、[Planner 综述](../planner/SUMMARY.md)。
