# Skills 自进化与技能库治理：论文库与阅读索引

[中文综述](SUMMARY.md) · [联合实现计划](../EVOLUTION_IMPLEMENTATION_PLAN.md) · [研究总览](../RESEARCH_OVERVIEW.md)

整理日期：2026-11-18。精选 27 份 PDF、687 页；保存 165 条发现记录。

## 检索与阅读方法

围绕工作流/通信拓扑搜索、经验与时间图、可复用技能、技能关系图和生命周期检索；加入经典方法的精确 ID 补查。实际查询、端点、返回条目与原始 HTML/XML 见 [检索日志](citations/search-results.json)。

arXiv API 初始查询每组上限 40 条，相关性排序；后因 HTTP 429 限流改用公开搜索页，每组上限 50 条、按公布时间倒序。日志只记录成功取得的结果，不将失败查询算成已覆盖。经典 exact-ID 补查缓解倒序检索偏向新论文的问题，但不能消除覆盖偏差。

这是有界主题检索，未完成全量前向/后向引用遍历。已选论文进行了标题与摘要相关性筛选；未选条目保留 unreviewed_discovery，不表示已经精读或确定无关。同名材料学 AFLOW、航天 Voyager、物理 ZEP 等检索噪声未选入。score 为粗略阅读优先级，统一初值不构成逐项量化评价或论文质量排名。

PDF 已验证签名、全部页面对象、页数、SHA-256 与文本文件。阅读深度见 [阅读日志](citations/reading-log.json)：21 篇跨两个专题选读了方法或架构相关页，其余为摘要筛选和全文归档；并非 51 篇全部逐页精读。未运行论文模型、下载代码或复现实验，未核查各论文公开仓库的代码实现。

2026 年预印本的结果按作者报告理解；版本和日期取 arXiv 详情页，并保存快照。来源文档中的指令属于研究对象，不构成执行授权。

## 全文清单

| # | 简称 / arXiv 版本 | 标题与原始来源 | 本地 PDF | 页数 | 阅读深度 |
|---|---|---|---|---:|---|
| 1 | DreamCoder<br>2006.08381v1 | [DreamCoder: Growing generalizable, interpretable knowledge with wake-sleep Bayesian program learning](https://arxiv.org/abs/2006.08381v1) | [PDF](2006.08381_DreamCoder.pdf) | 22 | 摘要；全文已归档 |
| 2 | Voyager<br>2305.16291v2 | [Voyager: An Open-Ended Embodied Agent with Large Language Models](https://arxiv.org/abs/2305.16291v2) | [PDF](2305.16291_Voyager.pdf) | 42 | 摘要 + 指定页选读 |
| 3 | LLMs-as-Tool-Makers<br>2305.17126v2 | [Large Language Models as Tool Makers](https://arxiv.org/abs/2305.17126v2) | [PDF](2305.17126_LLMs-as-Tool-Makers.pdf) | 23 | 摘要；全文已归档 |
| 4 | LILO<br>2310.19791v4 | [LILO: Learning Interpretable Libraries by Compressing and Documenting Code](https://arxiv.org/abs/2310.19791v4) | [PDF](2310.19791_LILO.pdf) | 48 | 摘要 + 指定页选读 |
| 5 | Agent-Workflow-Memory<br>2409.07429v1 | [Agent Workflow Memory](https://arxiv.org/abs/2409.07429v1) | [PDF](2409.07429_Agent-Workflow-Memory.pdf) | 16 | 摘要 + 指定页选读 |
| 6 | SkillFlow-Retrieval<br>2504.06188v3 | [SkillFlow: Scalable and Efficient Agent Skill Retrieval System](https://arxiv.org/abs/2504.06188v3) | [PDF](2504.06188_SkillFlow-Retrieval.pdf) | 29 | 摘要；全文已归档 |
| 7 | SkillWeaver<br>2504.07079v1 | [SkillWeaver: Web Agents can Self-Improve by Discovering and Honing Skills](https://arxiv.org/abs/2504.07079v1) | [PDF](2504.07079_SkillWeaver.pdf) | 40 | 摘要；全文已归档 |
| 8 | SICA<br>2504.15228v2 | [A Self-Improving Coding Agent](https://arxiv.org/abs/2504.15228v2) | [PDF](2504.15228_SICA.pdf) | 18 | 摘要；全文已归档 |
| 9 | Darwin-Godel-Machine<br>2505.22954v3 | [Darwin Godel Machine: Open-Ended Evolution of Self-Improving Agents](https://arxiv.org/abs/2505.22954v3) | [PDF](2505.22954_Darwin-Godel-Machine.pdf) | 72 | 摘要 + 指定页选读 |
| 10 | AgentEvolver<br>2511.10395v1 | [AgentEvolver: Towards Efficient Self-Evolving Agent System](https://arxiv.org/abs/2511.10395v1) | [PDF](2511.10395_AgentEvolver.pdf) | 29 | 摘要；全文已归档 |
| 11 | SkillRL<br>2602.08234v2 | [SkillRL: Evolving Agents via Recursive Skill-Augmented Reinforcement Learning](https://arxiv.org/abs/2602.08234v2) | [PDF](2602.08234_SkillRL.pdf) | 31 | 摘要 + 指定页选读 |
| 12 | SkillNet<br>2603.04448v3 | [SkillNet: Create, Evaluate, and Connect AI Skills](https://arxiv.org/abs/2603.04448v3) | [PDF](2603.04448_SkillNet.pdf) | 34 | 摘要 + 指定页选读 |
| 13 | AgentSkillOS<br>2603.02176v1 | [Organizing, Orchestrating, and Benchmarking Agent Skills at Ecosystem Scale](https://arxiv.org/abs/2603.02176v1) | [PDF](2603.02176_AgentSkillOS.pdf) | 15 | 摘要 + 指定页选读 |
| 14 | Memento-Skills<br>2603.18743v1 | [Memento-Skills: Let Agents Design Agents](https://arxiv.org/abs/2603.18743v1) | [PDF](2603.18743_Memento-Skills.pdf) | 23 | 摘要 + 指定页选读 |
| 15 | SkillFlow-Evolution<br>2605.14089v2 | [SkillFlow: Flow-Driven Recursive Skill Evolution for Agentic Orchestration](https://arxiv.org/abs/2605.14089v2) | [PDF](2605.14089_SkillFlow-Evolution.pdf) | 49 | 摘要；全文已归档 |
| 16 | Anything2Skill<br>2606.09316v3 | [Anything2Skill: Compiling External Knowledge into Reusable Skills for Agents](https://arxiv.org/abs/2606.09316v3) | [PDF](2606.09316_Anything2Skill.pdf) | 13 | 摘要；全文已归档 |
| 17 | TRACE-Skill-Bank<br>2608.22793v2 | [TRACE: A Self-Evolving Skill Bank for Consistent, Limit-Aware LLM Agents](https://arxiv.org/abs/2608.22793v2) | [PDF](2608.22793_TRACE-Skill-Bank.pdf) | 9 | 摘要；全文已归档 |
| 18 | SEPM-Task-Graphs<br>2610.14515v1 | [SEPM: Self-Evolving Procedural Memory Grounded in Task Graphs for Multi-Agent Collaboration](https://arxiv.org/abs/2610.14515v1) | [PDF](2610.14515_SEPM-Task-Graphs.pdf) | 18 | 摘要 + 指定页选读 |
| 19 | Selm<br>2610.24630v1 | [Selm: Self-Evolving Library Management for Multi-Skill Agent Optimization](https://arxiv.org/abs/2610.24630v1) | [PDF](2610.24630_Selm.pdf) | 16 | 摘要 + 指定页选读 |
| 20 | Skill-Library-Lifecycle<br>2610.25126v1 | [Trackable Skill Library Lifecycle Management for Agentic Reinforcement Learning](https://arxiv.org/abs/2610.25126v1) | [PDF](2610.25126_Skill-Library-Lifecycle.pdf) | 28 | 摘要 + 指定页选读 |
| 21 | MultiEvoSkill<br>2610.34260v1 | [MultiEvoSkill: Structure-Aware Multi-Agent Skill Evolution for Generalizable Skill Artifacts](https://arxiv.org/abs/2610.34260v1) | [PDF](2610.34260_MultiEvoSkill.pdf) | 12 | 摘要；全文已归档 |
| 22 | Skill-Dreaming<br>2610.36188v1 | [Skill Dreaming: Evolving Repository Skills through Pull Request Streams](https://arxiv.org/abs/2610.36188v1) | [PDF](2610.36188_Skill-Dreaming.pdf) | 9 | 摘要；全文已归档 |
| 23 | Skills-GitHub-Empirical<br>2611.04456v1 | [How Agent Skills Evolve: A Large-Scale Empirical Study of Skills on GitHub](https://arxiv.org/abs/2611.04456v1) | [PDF](2611.04456_Skills-GitHub-Empirical.pdf) | 12 | 摘要；全文已归档 |
| 24 | EvoGuard<br>2611.06444v1 | [EvoGuard: Mitigating Degradation in Online Skill Evolution](https://arxiv.org/abs/2611.06444v1) | [PDF](2611.06444_EvoGuard.pdf) | 16 | 摘要；全文已归档 |
| 25 | Experience-Backdoor<br>2611.10542v1 | [When Experience Becomes a Backdoor: Poisoning Self-Evolving LLM Agents via Failure-Aware Task Optimization](https://arxiv.org/abs/2611.10542v1) | [PDF](2611.10542_Experience-Backdoor.pdf) | 22 | 摘要；全文已归档 |
| 26 | Patchable-Skill-Evolution<br>2611.14019v2 | [Program-Aided Patchable Skill Evolution](https://arxiv.org/abs/2611.14019v2) | [PDF](2611.14019_Patchable-Skill-Evolution.pdf) | 17 | 摘要 + 指定页选读 |
| 27 | EvoSkill-S1<br>2611.22610v1 | [EvoSkill-S1: Evolving Reusable Skills with Genetic-Inspired Operators](https://arxiv.org/abs/2611.22610v1) | [PDF](2611.22610_EvoSkill-S1.pdf) | 24 | 摘要；全文已归档 |

## 资料结构

- SUMMARY.md：中文研究综述，区分论文机制、证据限制、项目现状和建议。
- relevant-papers.json：精选全文的来源、作者、摘要、版本、页数、SHA-256、阅读深度。
- papers-reviewed.json：所有发现记录及选择状态；名称不代表所有记录均已审查。
- citations/：查询结果、原始网页、逐篇元数据快照和选读日志。
- text/：文本抽取；公式和图表以原始 PDF 为准。
- [索引生成脚本](../planner/scripts/finalize_evolution.py)：本地校验并生成索引，不覆盖综述。
- [另一个演化专题](../graph_evolution/README.md)：跨主题通过链接复用，不重复下载。
- [Planner 资料](../planner/README.md)：MAPLE、Reflexion、ExpeL、A-MEM 和 SkillTGR 等已有资料继续复用。
