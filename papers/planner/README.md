# Planner 论文库与阅读索引

[阅读中文综述：从表格问答到经验驱动的自适应规划](SUMMARY.md)

新增专题：[差分隐私](../differential_privacy/SUMMARY.md) · [本地前导网络](../leading_model/SUMMARY.md) · [意图理解前导模型](../intent_model/SUMMARY.md) · [全部研究总览](../RESEARCH_OVERVIEW.md)

整理日期：2026-11-18。共 44 份有效 PDF：原有种子论文 5 份，新增下载 39 份；合计 1001 页。ST-Raptor 包含方法论文与系统短文两个版本。

## 阅读顺序

先阅读 MACT 与 TALON，理解规划、执行与数据访问；再阅读 Table-Critic 与 MAPLE，理解局部修复和经验归档；最后阅读 DTR 与 ST-Raptor，理解层级表结构与路径选择。实现细节和项目接入建议均在 SUMMARY.md 中。

## 全文清单

| # | 简称 | 论文标题与来源 | 本地 PDF | 页数 | 阅读深度 |
|---|---|---|---|---:|---|
| 1 | MAPLE | [MAPLE: Multi-Agent Adaptive Planning with Long-Term Memory for Table Reasoning](https://arxiv.org/abs/2506.05813v2) | [PDF](MAPLE.pdf) | 27 | 重点阅读方法、实验及附录 |
| 2 | MACT | [Efficient Multi-Agent Collaboration with Tool Use for Online Planning in Complex Table Question Answering](https://aclanthology.org/2025.findings-naacl.54/) | [PDF](MACT_Findings-NAACL2025.pdf) | 24 | 重点阅读方法、实验及附录 |
| 3 | Table-Critic | [Table-Critic: A Multi-Agent Framework for Collaborative Criticism and Refinement in Table Reasoning](https://aclanthology.org/2025.acl-long.853/) | [PDF](Table-Critic_ACL2025.pdf) | 20 | 重点阅读方法、实验及附录 |
| 4 | TALON | [TALON: A Multi-Agent Framework for Long-Table Exploration and Question Answering](https://aclanthology.org/2025.emnlp-main.1393/) | [PDF](TALON_EMNLP2025.pdf) | 17 | 重点阅读方法、实验及附录 |
| 5 | DTR | [Deep Tabular Research via Continual Experience-Driven Execution](https://arxiv.org/abs/2603.09151v2) | [PDF](Deep-Tabular-Research_arXiv2026.pdf) | 23 | 重点阅读方法、实验及附录 |
| 6 | AutoTQA | [AutoTQA: Towards Autonomous Tabular Question Answering through Multi-Agent Large Language Models](https://doi.org/10.14778/3685800.3685816) | [PDF](2024_AutoTQA.pdf) | 14 | 摘要与方法选读 |
| 7 | TaPERA | [TaPERA: Enhancing Faithfulness and Interpretability in Long-Form Table QA by Content Planning and Execution-based Reasoning](https://aclanthology.org/2024.acl-long.692/) | [PDF](2024_TaPERA.pdf) | 17 | 摘要与方法选读 |
| 8 | ReAct | [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629v3) | [PDF](2210.03629_ReAct.pdf) | 33 | 摘要筛选；已下载全文 |
| 9 | Binder | [Binding Language Models in Symbolic Languages](https://arxiv.org/abs/2210.02875v2) | [PDF](2210.02875_Binder.pdf) | 27 | 摘要与方法选读 |
| 10 | Dater | [Large Language Models are Versatile Decomposers: Decompose Evidence and Questions for Table-based Reasoning](https://arxiv.org/abs/2301.13808v3) | [PDF](2301.13808_Dater.pdf) | 16 | 摘要与方法选读 |
| 11 | Reflexion | [Reflexion: Language Agents with Verbal Reinforcement Learning](https://arxiv.org/abs/2303.11366v4) | [PDF](2303.11366_Reflexion.pdf) | 19 | 摘要筛选；已下载全文 |
| 12 | ExpeL | [ExpeL: LLM Agents Are Experiential Learners](https://arxiv.org/abs/2308.10144v3) | [PDF](2308.10144_ExpeL.pdf) | 38 | 摘要筛选；已下载全文 |
| 13 | ReAcTable | [ReAcTable: Enhancing ReAct for Table Question Answering](https://arxiv.org/abs/2310.00815v1) | [PDF](2310.00815_ReAcTable.pdf) | 14 | 摘要与方法选读 |
| 14 | Chain-of-Table | [Chain-of-Table: Evolving Tables in the Reasoning Chain for Table Understanding](https://arxiv.org/abs/2401.04398v2) | [PDF](2401.04398_Chain-of-Table.pdf) | 24 | 摘要与方法选读 |
| 15 | LLM-Agent-Planning-Survey | [Understanding the planning of LLM agents: A survey](https://arxiv.org/abs/2402.02716v1) | [PDF](2402.02716_LLM-Agent-Planning-Survey.pdf) | 9 | 摘要筛选；已下载全文 |
| 16 | TabSQLify | [TabSQLify: Enhancing Reasoning Capabilities of LLMs Through Table Decomposition](https://arxiv.org/abs/2404.10150v1) | [PDF](2404.10150_TabSQLify.pdf) | 13 | 摘要与方法选读 |
| 17 | TableRAG | [TableRAG: Million-Token Table Understanding with Language Models](https://arxiv.org/abs/2410.04739v3) | [PDF](2410.04739_TableRAG.pdf) | 23 | 摘要与方法选读 |
| 18 | A-MEM | [A-MEM: Agentic Memory for LLM Agents](https://arxiv.org/abs/2502.12110v11) | [PDF](2502.12110_A-MEM.pdf) | 28 | 摘要筛选；已下载全文 |
| 19 | RealHiTBench | [RealHiTBench: A Comprehensive Realistic Hierarchical Table Benchmark for Evaluating LLM-Based Table Analysis](https://arxiv.org/abs/2506.13405v2) | [PDF](2506.13405_RealHiTBench.pdf) | 33 | 摘要筛选；已下载全文 |
| 20 | ST-Raptor | [ST-Raptor: LLM-Powered Semi-Structured Table Question Answering](https://arxiv.org/abs/2508.18190v3) | [PDF](2508.18190_ST-Raptor.pdf) | 16 | 摘要与方法选读 |
| 21 | Octopus | [Octopus: Agentic Multi-Table Discovery over Tabular Data Lakes](https://arxiv.org/abs/2601.02304v2) | [PDF](2601.02304_Octopus.pdf) | 13 | 摘要筛选；已下载全文 |
| 22 | ST-Raptor-System | [ST-Raptor: An Agentic System for Semi-Structured Table QA](https://arxiv.org/abs/2602.07034v1) | [PDF](2602.07034_ST-Raptor-System.pdf) | 4 | 摘要筛选；已下载全文 |
| 23 | MATA | [MATA: Multi-Agent Framework for Reliable and Flexible Table Question Answering](https://arxiv.org/abs/2602.09642v2) | [PDF](2602.09642_MATA.pdf) | 41 | 摘要筛选；已下载全文 |
| 24 | TraceBack | [TraceBack: Multi-Agent Decomposition for Fine-Grained Table Attribution](https://arxiv.org/abs/2602.13059v1) | [PDF](2602.13059_TraceBack.pdf) | 17 | 摘要筛选；已下载全文 |
| 25 | TabTracer | [TabTracer: Monte Carlo Tree Search for Complex Table Reasoning with Large Language Models](https://arxiv.org/abs/2602.14089v1) | [PDF](2602.14089_TabTracer.pdf) | 14 | 摘要筛选；已下载全文 |
| 26 | QUIETT | [QUIETT: Query-Independent Table Transformation for Robust Reasoning](https://arxiv.org/abs/2602.20017v2) | [PDF](2602.20017_QUIETT.pdf) | 21 | 摘要与方法选读 |
| 27 | TableMind-Plus-Plus | [TableMind++: An Uncertainty-Aware Programmatic Agent for Tool-Augmented Table Reasoning](https://arxiv.org/abs/2603.07528v2) | [PDF](2603.07528_TableMind-Plus-Plus.pdf) | 27 | 摘要筛选；已下载全文 |
| 28 | DataFactory | [DataFactory: Collaborative Multi-Agent Framework for Advanced Table Question Answering](https://arxiv.org/abs/2603.09152v1) | [PDF](2603.09152_DataFactory.pdf) | 34 | 摘要筛选；已下载全文 |
| 29 | TABQAWORLD | [TABQAWORLD: Optimizing Multimodal Reasoning for Multi-Turn Table Question Answering](https://arxiv.org/abs/2604.03393v1) | [PDF](2604.03393_TABQAWORLD.pdf) | 41 | 摘要筛选；已下载全文 |
| 30 | TABALIGN | [From Table to Cell: Attention for Better Reasoning with TABALIGN](https://arxiv.org/abs/2605.14465v2) | [PDF](2605.14465_TABALIGN.pdf) | 54 | 摘要筛选；已下载全文 |
| 31 | TabClaw | [TabClaw: An Interactive and Self-Evolving Agent for Spreadsheet Manipulation and Table Reasoning](https://arxiv.org/abs/2606.10316v1) | [PDF](2606.10316_TabClaw.pdf) | 5 | 摘要与方法选读 |
| 32 | SkillTGR | [Evolving from Lessons: Skill-Augmented Table Graph Reasoning for Operation-wise Table Question Answering](https://arxiv.org/abs/2607.22633v2) | [PDF](2607.22633_SkillTGR.pdf) | 14 | 摘要与方法选读 |
| 33 | GRAB-Latent-Bridges | [Latent Bridges for Multi-Table Question Answering](https://arxiv.org/abs/2606.28916v3) | [PDF](2606.28916_GRAB-Latent-Bridges.pdf) | 28 | 摘要筛选；已下载全文 |
| 34 | ProgramTab | [ProgramTab: Boosting Table Reasoning of LLMs via Programmatic Paradigm](https://arxiv.org/abs/2607.11207v1) | [PDF](2607.11207_ProgramTab.pdf) | 12 | 摘要筛选；已下载全文 |
| 35 | Semantic-Answerability-Gap | [Semantically Similar, Yet Not Answerable: Diagnosing the Semantic-Answerability Gap in Table RAG](https://arxiv.org/abs/2607.17742v2) | [PDF](2607.17742_Semantic-Answerability-Gap.pdf) | 50 | 摘要筛选；已下载全文 |
| 36 | PARTAB | [PARTAB: Partition-Aware Reasoning with Structured Evidence for Scalable Table Understanding](https://arxiv.org/abs/2608.24082v1) | [PDF](2608.24082_PARTAB.pdf) | 21 | 摘要筛选；已下载全文 |
| 37 | H2Table | [H2Table: Hierarchical Hypergraph-Enhanced Large Language Models for Complex Table Reasoning](https://arxiv.org/abs/2609.01216v2) | [PDF](2609.01216_H2Table.pdf) | 12 | 摘要筛选；已下载全文 |
| 38 | TabScope | [TabScope: Question-Adaptive Scope Selection for Table Question Answering](https://arxiv.org/abs/2609.03395v2) | [PDF](2609.03395_TabScope.pdf) | 17 | 摘要筛选；已下载全文 |
| 39 | TableSeek | [TableSeek: Structure-Preserving Agentic Evidence Seeking over Heterogeneous Table Corpora](https://arxiv.org/abs/2609.34157v1) | [PDF](2609.34157_TableSeek.pdf) | 37 | 摘要筛选；已下载全文 |
| 40 | ComInsight | [Structured Composition of Verifiable Atomic Insights for Table-to-Report Generation](https://arxiv.org/abs/2610.03525v1) | [PDF](2610.03525_ComInsight.pdf) | 13 | 摘要筛选；已下载全文 |
| 41 | GBDI-Imperfect-Tables | [Understanding Errors in LLM-Based Question Answering over Imperfect Tables](https://arxiv.org/abs/2610.04687v2) | [PDF](2610.04687_GBDI-Imperfect-Tables.pdf) | 41 | 摘要筛选；已下载全文 |
| 42 | Cost-Effective-Numerical-QA | [Cost-Effective Numerical QA over Semi-Structured Table: Structuring, Resolution, Planning](https://arxiv.org/abs/2610.07749v1) | [PDF](2610.07749_Cost-Effective-Numerical-QA.pdf) | 21 | 摘要筛选；已下载全文 |
| 43 | Data-Readme | [Data.Readme: Documenting Table Relationships for Diverse Data Tasks](https://arxiv.org/abs/2610.25131v1) | [PDF](2610.25131_Data-Readme.pdf) | 14 | 摘要与方法选读 |
| 44 | EviDARL | [EviDARL: Evidence-Centric Dual-Agent Reasoning via Alternating Reinforcement Learning for Multi-Table Question Answering](https://arxiv.org/abs/2611.22310v1) | [PDF](2611.22310_EviDARL.pdf) | 15 | 摘要与方法选读 |

## 检索与筛选

- 去重记录 185 条，已选下载 44 份（含 5 份种子）；“可能扩展”不等于全文已读。
- 使用 arXiv 四组查询，每组最多 60 条；按提交时间排序。基础查询漏掉的经典工作用精确 ID 补查。ACL/VLDB 的两篇补充通过出版来源下载。
- 宽泛词匹配存在无关结果。已人工选择本次重点，其他记录的初筛状态为启发式标记，不宣称 185 条均经过独立人工摘要审查。
- 原始查询、结果元数据和时间保存在 citations/search-results.json 及对应 XML。检索不是全球穷尽搜索。
- 评分只表示本主题优先级；新增精选一般为 8/10，直接核心补充为 9/10，用户种子为 10/10。
- 验证了每个 PDF 的签名、可打开性、页数和 SHA-256；没有运行论文模型或执行下载的外部脚本。

## 文件与复现

- SUMMARY.md：中文研究文章，含方法对比、实验口径、实现建议、项目接口映射和验证计划。
- papers-reviewed.json：全部发现记录、来源、下载状态、版本、阅读深度和校验摘要。
- relevant-papers.json：44 份已收录材料的结构化子集。
- citations/citation-graph.json：从种子全文名称匹配提取的候选引用关系；不能视为逐条核实的完整引用图，未完成全量前向引用遍历。
- citations/：原始检索响应、公开 README 和实际读取的源文件文本快照。
- text/：PDF 抽取文本与种子方法图检查图；供定位，版式与公式以 PDF 为准。
- scripts/retrieve_literature.py：重做检索或按现有清单补齐下载；scripts/finalize_catalog.py：验证和生成索引。
- build_catalog.py 会重建初始清单；再次运行前应保存已有人工阅读标记，避免覆盖。

新增论文按检索时的 arXiv 版本记录；清单中的预印本不自动等同于正式录用版本。代码仓库只核查了文中说明的入口，未完成运行复现。
