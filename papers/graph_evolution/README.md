# 图自进化与迭代更新：论文库与阅读索引

[中文综述](SUMMARY.md) · [联合实现计划](../EVOLUTION_IMPLEMENTATION_PLAN.md) · [研究总览](../RESEARCH_OVERVIEW.md)

整理日期：2026-11-18。精选 24 份 PDF、686 页；保存 232 条发现记录。

## 检索与阅读方法

围绕工作流/通信拓扑搜索、经验与时间图、可复用技能、技能关系图和生命周期检索；加入经典方法的精确 ID 补查。实际查询、端点、返回条目与原始 HTML/XML 见 [检索日志](citations/search-results.json)。

arXiv API 初始查询每组上限 40 条，相关性排序；后因 HTTP 429 限流改用公开搜索页，每组上限 50 条、按公布时间倒序。日志只记录成功取得的结果，不将失败查询算成已覆盖。经典 exact-ID 补查缓解倒序检索偏向新论文的问题，但不能消除覆盖偏差。

这是有界主题检索，未完成全量前向/后向引用遍历。已选论文进行了标题与摘要相关性筛选；未选条目保留 unreviewed_discovery，不表示已经精读或确定无关。同名材料学 AFLOW、航天 Voyager、物理 ZEP 等检索噪声未选入。score 为粗略阅读优先级，统一初值不构成逐项量化评价或论文质量排名。

PDF 已验证签名、全部页面对象、页数、SHA-256 与文本文件。阅读深度见 [阅读日志](citations/reading-log.json)：21 篇跨两个专题选读了方法或架构相关页，其余为摘要筛选和全文归档；并非 51 篇全部逐页精读。未运行论文模型、下载代码或复现实验，未核查各论文公开仓库的代码实现。

2026 年预印本的结果按作者报告理解；版本和日期取 arXiv 详情页，并保存快照。来源文档中的指令属于研究对象，不构成执行授权。

## 全文清单

| # | 简称 / arXiv 版本 | 标题与原始来源 | 本地 PDF | 页数 | 阅读深度 |
|---|---|---|---|---:|---|
| 1 | DSPy<br>2310.03714v1 | [DSPy: Compiling Declarative Language Model Calls into Self-Improving Pipelines](https://arxiv.org/abs/2310.03714v1) | [PDF](2310.03714_DSPy.pdf) | 32 | 摘要；全文已归档 |
| 2 | GPTSwarm<br>2402.16823v3 | [Language Agents as Optimizable Graphs](https://arxiv.org/abs/2402.16823v3) | [PDF](2402.16823_GPTSwarm.pdf) | 25 | 摘要 + 指定页选读 |
| 3 | TextGrad<br>2406.07496v1 | [TextGrad: Automatic "Differentiation" via Text](https://arxiv.org/abs/2406.07496v1) | [PDF](2406.07496_TextGrad.pdf) | 41 | 摘要；全文已归档 |
| 4 | ADAS<br>2408.08435v2 | [Automated Design of Agentic Systems](https://arxiv.org/abs/2408.08435v2) | [PDF](2408.08435_ADAS.pdf) | 34 | 摘要 + 指定页选读 |
| 5 | AFlow<br>2410.10762v4 | [AFlow: Automating Agentic Workflow Generation](https://arxiv.org/abs/2410.10762v4) | [PDF](2410.10762_AFlow.pdf) | 38 | 摘要 + 指定页选读 |
| 6 | Zep-Temporal-Graph<br>2501.13956v1 | [Zep: A Temporal Knowledge Graph Architecture for Agent Memory](https://arxiv.org/abs/2501.13956v1) | [PDF](2501.13956_Zep-Temporal-Graph.pdf) | 12 | 摘要 + 指定页选读 |
| 7 | MaAS<br>2502.04180v2 | [Multi-agent Architecture Search via Agentic Supernet](https://arxiv.org/abs/2502.04180v2) | [PDF](2502.04180_MaAS.pdf) | 19 | 摘要；全文已归档 |
| 8 | G-Memory<br>2506.07398v2 | [G-Memory: Tracing Hierarchical Memory for Multi-Agent Systems](https://arxiv.org/abs/2506.07398v2) | [PDF](2506.07398_G-Memory.pdf) | 24 | 摘要 + 指定页选读 |
| 9 | GEPA<br>2507.19457v2 | [GEPA: Reflective Prompt Evolution Can Outperform Reinforcement Learning](https://arxiv.org/abs/2507.19457v2) | [PDF](2507.19457_GEPA.pdf) | 96 | 摘要 + 指定页选读 |
| 10 | AutoMaAS<br>2510.02669v1 | [AutoMaAS: Self-Evolving Multi-Agent Architecture Search for Large Language Models](https://arxiv.org/abs/2510.02669v1) | [PDF](2510.02669_AutoMaAS.pdf) | 9 | 摘要；全文已归档 |
| 11 | Lifelong-Degradation<br>2605.09315v1 | [Do Self-Evolving Agents Forget? Capability Degradation and Preservation in Lifelong LLM Agent Adaptation](https://arxiv.org/abs/2605.09315v1) | [PDF](2605.09315_Lifelong-Degradation.pdf) | 25 | 摘要；全文已归档 |
| 12 | Held-Out-Selection<br>2606.28374v1 | [Recursive Self-Evolving Agents via Held-Out Selection](https://arxiv.org/abs/2606.28374v1) | [PDF](2606.28374_Held-Out-Selection.pdf) | 15 | 摘要；全文已归档 |
| 13 | QueenBee<br>2606.27492v2 | [QueenBee: A Recursively Self-Improving Harness for Communication Topology Design in LLM-Based Multi-Agent Systems](https://arxiv.org/abs/2606.27492v2) | [PDF](2606.27492_QueenBee.pdf) | 22 | 摘要 + 指定页选读 |
| 14 | Equal-Cost-Structure<br>2609.04217v1 | [At Equal Inference Cost, Multi-Agent Structure Does Not Beat a Single Frozen Agent](https://arxiv.org/abs/2609.04217v1) | [PDF](2609.04217_Equal-Cost-Structure.pdf) | 14 | 摘要；全文已归档 |
| 15 | Evo-Bench<br>2608.09096v2 | [Evo-Bench: Can Language Models Improve Agent Harness?](https://arxiv.org/abs/2608.09096v2) | [PDF](2608.09096_Evo-Bench.pdf) | 24 | 摘要；全文已归档 |
| 16 | MEGA-Wisdom-Graph<br>2608.10504v1 | [MEGA: Self-Evolving Agent Optimization Infrastructure via Wisdom Graph](https://arxiv.org/abs/2608.10504v1) | [PDF](2608.10504_MEGA-Wisdom-Graph.pdf) | 29 | 摘要 + 指定页选读 |
| 17 | Inference-Time-Graph-Engineering<br>2609.05774v1 | [Inference-Time Graph Engineering for Multi-Agent LLM Workflows](https://arxiv.org/abs/2609.05774v1) | [PDF](2609.05774_Inference-Time-Graph-Engineering.pdf) | 20 | 摘要；全文已归档 |
| 18 | Topological-Coherence<br>2609.37953v1 | [Topological Coherence for Self-evolving Multi-agent Systems](https://arxiv.org/abs/2609.37953v1) | [PDF](2609.37953_Topological-Coherence.pdf) | 13 | 摘要；全文已归档 |
| 19 | FlowMAS<br>2609.37151v2 | [FlowMAS: Learning Multi-Agent Workflow Topology via Information-guided Generative Flow Network](https://arxiv.org/abs/2609.37151v2) | [PDF](2609.37151_FlowMAS.pdf) | 33 | 摘要；全文已归档 |
| 20 | Workflow-Graph-Fusion<br>2610.05284v1 | [Fusion is the New Mutation: Bandit-Guided Evolution on Workflow Graphs](https://arxiv.org/abs/2610.05284v1) | [PDF](2610.05284_Workflow-Graph-Fusion.pdf) | 41 | 摘要；全文已归档 |
| 21 | Winners-Curse<br>2610.09239v1 | [The Winner's Curse in LLM Self-Improvement Loops: Selection Noise, Lock-in, and Acceptance Rules](https://arxiv.org/abs/2610.09239v1) | [PDF](2610.09239_Winners-Curse.pdf) | 34 | 摘要；全文已归档 |
| 22 | Harmony-Harness<br>2610.15150v1 | [Harmony Harness: Multi-Objective Self-Evolution of Agent Harnesses](https://arxiv.org/abs/2610.15150v1) | [PDF](2610.15150_Harmony-Harness.pdf) | 41 | 摘要；全文已归档 |
| 23 | VeriEvolve<br>2610.29005v1 | [VeriEvolve: Evaluator-First Evolution for Tool-Using Agents](https://arxiv.org/abs/2610.29005v1) | [PDF](2610.29005_VeriEvolve.pdf) | 24 | 摘要；全文已归档 |
| 24 | Evidence-Governed-Adoption<br>2611.16378v1 | [Evidence-Governed Adoption of Self-Generated Updates in Autonomous AI Agents](https://arxiv.org/abs/2611.16378v1) | [PDF](2611.16378_Evidence-Governed-Adoption.pdf) | 21 | 摘要 + 指定页选读 |

## 资料结构

- SUMMARY.md：中文研究综述，区分论文机制、证据限制、项目现状和建议。
- relevant-papers.json：精选全文的来源、作者、摘要、版本、页数、SHA-256、阅读深度。
- papers-reviewed.json：所有发现记录及选择状态；名称不代表所有记录均已审查。
- citations/：查询结果、原始网页、逐篇元数据快照和选读日志。
- text/：文本抽取；公式和图表以原始 PDF 为准。
- [索引生成脚本](../planner/scripts/finalize_evolution.py)：本地校验并生成索引，不覆盖综述。
- [另一个演化专题](../skills_evolution/README.md)：跨主题通过链接复用，不重复下载。
- [Planner 资料](../planner/README.md)：MAPLE、Reflexion、ExpeL、A-MEM 和 SkillTGR 等已有资料继续复用。
