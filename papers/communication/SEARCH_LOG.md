# 检索与筛选方法记录

日期：2026-11-25；主题：LLM多智能体的通信选择、原始证据按需获取、上下文管理与可靠性。

## 1. 研究范围

围绕三个问题收集证据：已有方法如何减少交流；如何选择、恢复和使用证据；哪些尚可验证的问题与项目接口对应。默认目标是结合现有项目的扎实方法或系统论文，没有先固定投稿会议。

主语料38篇：18篇定向选读正文，20篇标题／摘要筛选。候选问题反向检索再补充3篇边界文献，均为摘要层。合计核对41篇主题材料，另有1篇流程工具来源M01。语料选择截至2026-11-25；没有下载或引用晚于该日发表的工作。

本轮既包含直接LLM多Agent方法，也纳入相邻的主动检索、单Agent上下文管理、证据引用和失败评测。机器人／无线网络中的通信资源分配、只有名称相近的文章、媒体解读与厂商宣传不作为核心方法证据。

## 2. 来源与操作

- **发现**：通用学术网页检索，以arXiv、ACL Anthology、OpenReview等官方页面为主。
- **元数据核查**：逐条访问精确论文页，核对标题、作者、首次日期、版本和摘要；同名缩写按标题与持久ID区分。
- **正文选读**：优先arXiv HTML的方法、实验设置、关键结果和局限；18篇的具体范围见[READING_LOG.md](READING_LOG.md)。取回但未实际检查的部分不算精读。
- **追踪**：AOD等近邻的Related Work和References用于补查；同时在取回的参考文献中匹配主语料标题，得到66条有锚点的语料内引用。
- **交叉来源**：部分论文在OpenReview命中用于书目信息交叉检查，不将审稿讨论或检索摘要当作独立效果验证。

未调用需要注册的商用学术API，没有使用虚构邮箱，没有绕过付费墙。主语料由公开摘要与公开正文构成。

## 3. 主要检索字符串

以下保留本轮的主要查询；同一行的查询分别提交，不表示数据库支持整行布尔语法。第一组探索查询有部分未返回可用内容，未据其空结果推断研究不存在。通用搜索未导出完整排序命中列表，因此不报告未经记录的总命中量，也不绘制伪造的PRISMA筛选数量。

| 轮次 | 查询字符串 |
|---|---|
| 01 初始范围 | `multi agent LLM communication AgentPrune Cut the Crap`；`AgentDropout KVComm multi agent communication`；`multi agent receiver driven on demand communication evidence retrieval budget context` |
| 02 正式来源 | `site.aclanthology.org "Cut the Crap"`；`site.aclanthology.org "AgentDropout"`；`site.arxiv.org "KVComm"`；`site.arxiv.org "Need-to-Know" "Multi-Agent"` |
| 03 通信自适应 | `"AgentPrune" "Cut the"`；`LLM multi agent communication "on-demand" "retrieval"`；`"multi-agent" "communication" "budget" "2026"`；`"Need-to-Know" agents communication` |
| 04 近邻精确标题 | `"Cut the Crap: An Economical Communication Pipeline"`；`"Ask on Demand: Targeted Peer Communication"`；`"What Should Agents Say?"`；`"AgentPrune"` |
| 05 共享与来源 | `"AgentFugue"`；`"LLM" "Learning to Share" agents memory`；`"multi-agent" "evidence" "provenance" communication`；`"Silo-Bench"` |
| 06 共享与泛化 | `"Learning to Share: Selective Memory for Efficient Parallel Agentic Systems"`；`"AgentRound" communication`；`"AgentConductor"`；`"AgentBoard" information asymmetry communication benchmark` |
| 07 上下文与失败 | `"DynaComm" LLM`；`"communication" "prompt pruning" agents`；`"recursive language models"`；`"Why Do Multi-Agent LLM Systems Fail"` |
| 08 检索与剪枝 | `"multi-agent" "communication" "compression" site:aclanthology.org/2025`；`"DynaComm" "agent"`；`"Inter-Agent" "Pruning"`；`"Adaptive-RAG"` |
| 09 评测与来源 | `"Context Compression for LLM Agents: A Survey of Methods, Failure Modes, and Evaluation"`；`"LLM multi-agent" "communication" "adaptive" "pruning" DynaComm`；`"From Agent Traces to Trust"`；`"Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents"` |
| 10 成本与停止 | `"Beyond Token Savings: A Systematic Study of Context Compression in LLM Agents"`；`"DynaComm" "LLM" communication`；`"Stop" "evidence sufficiency" retrieval agents`；`"Generating Text with Citations" ALCE` |
| 11 书目复核 | `AgentDropout paper ACL 2025`；`Silo-Bench multi agent benchmark`；`"What Should Agents Say?"`；`"Beyond Token Savings"` |
| 12 停止与压缩 | `"HALT-RAG"`；`"BELIEFRAG"`；`"Beyond Token Savings" context compression`；`"Context Compression for LLM Agents"` |
| 13 交接与潜表示 | `"Semantic Context Handoff"`；`"KVComm" layers`；`"LatCom" agents`；`"Ask on Demand: Targeted Peer Communication"` |
| 14 OpenReview补查 | `"Cut the Crap" site:openreview.net`；`"Learning to Share: Selective Memory" site:openreview.net`；`"KVCOMM" site:openreview.net`；`"Why Do Multi-Agent LLM Systems Fail?" site:openreview.net` |
| 15 公开实现线索 | `"AgentPrune" github`；`"Ask on Demand" "github"`；`"The Missing Complement" "github"`；`"Semantic Context Handoff" "github"` |
| 16 对候选问题反向检索 | `"multi-agent" "evidence" "pagination"`；`"agents" "communication" "evidence sufficiency"`；`"multi-agent" "version-aware" "context"`；`"multi-agent" "communication" "evidence completeness"` |
| 17 边界补充 | `"Not All Evidence Is Admissible: Evidence Governance for Tool-Augmented Medical Agents"`；`"Can Multi-Agents Think Like Lawyers?"`；`"Policy-Controlled Offline-Verifiable Accountability"`；`"Measuring Consensus" "Jin Gao"` |

精确源页的实际取回列表固定在`scripts/collect_review_sources.py`的`SEEDS`中；持久元数据另见[REFERENCES.md](REFERENCES.md)。正文和页面SHA-256保留在本地`papers-reviewed.json`，方便区分后续网页版本变化。

## 4. 纳入与阅读分级

**核心纳入：** 能直接解释或比较通信拓扑、消息选择、接收方需求、原证据访问、证据充分性、上下文管理、成本或失败原因的方法／系统／基准。优先正文可获取、有清楚方法或评测的工作。

**背景纳入：** 必要的通用Agent框架和协议综述；只用于范围与概念边界，不作为候选策略效果的主要对手。

**未纳入主矩阵：** 新闻、社交媒体、聚合页、缺少可核对原始记录的名称线索，以及与当前证据获取问题距离较远的机器人／网络优化工作。检索中出现的AgentRound、AgentConductor、DynaComm、HALT-RAG等名称若未进入目录，不能据此判断其不存在或不相关；本轮没有对这些未形成记录的线索作效果结论。

相关性按主题匹配0—3、可用方法／评测0—4、项目针对性0—3作人工优先级判断。它不是论文质量、正确性或创新性的评分。34篇主语料得分至少7，4篇留作外围背景；高相关也不意味着已充分阅读全文。

## 5. 最近邻与补充文献

主语料以AOD、MSS-Complement、SCH、PACT、LTS和AgentFugue为核心，再向检索、压缩、评测和来源追踪扩展。严格区分两篇KVComm：2510.12872与2510.03346；不能按缩写去重。正文页面能返回HTTP 200也不足以确认文献，采集脚本同时检查预期标题片段。

<a id="supplementary"></a>

候选问题的反向检索另外筛查了以下3篇，均核对摘要，但未定向阅读正文，因此不并入主矩阵38篇：

| ID | 来源与日期 | 对本轮问题的影响 | 阅读边界 |
|---|---|---|---|
| S01 | [Not All Evidence Is Admissible](https://arxiv.org/abs/2611.22169)，2026-11-17 | 医疗工具输出的独立证据准入；提示“限制什么可以进入证据上下文”也已有直接研究 | 摘要层；不能外推其效用到所有多Agent任务 |
| S02 | [Policy-Controlled Offline-Verifiable Accountability](https://arxiv.org/abs/2608.28542)，2026-08起，11-09修订 | 跨组织消息的签名、授权、回执及离线证据包；属于审计问责语义 | 摘要层；其evidence sufficiency不是任务答案的语义充分性 |
| S03 | [Measuring Consensus in AI Agent Networks](https://arxiv.org/abs/2610.24833)，2026-10-17 | 将共识轨迹、信息与正确答案分开评测；进一步支持内部协同诊断 | 摘要层；不能从共识收敛直接推断真实性 |

另发现匿名OpenReview稿件[Can Multi-Agents Think Like Lawyers? A Benchmark for Legal Multi-Agent Reasoning](https://openreview.net/pdf?id=YqZhobm9q5)。本轮未确认稳定作者、版本和发表状态，保留为法律领域后续线索，不纳入核对论文数，也不引用其结果。

## 6. 可以与不可以复查的内容

可以复查：精确源页、元数据、主语料筛选理由、18篇阅读范围、66条语料内引用、项目代码依据和生成脚本。核心记录同时保留为Markdown，避免研究JSON未进入Git导致结论丢失。

未完成：所有数据库的全量导出、逐条搜索命中的完整排除表、双人独立筛选、完整前向引用遍历、全部论文代码审计、训练数据泄漏审计、论文复现及效果再统计。OpenReview的出现不等于录用，作者提供代码链接也不等于本轮已验证可运行。

由于这些边界，本轮适合确定近邻和收窄研究问题；不适合支持“首次提出”“全面优于现有方法”或“研究空白已经证明”的陈述。
