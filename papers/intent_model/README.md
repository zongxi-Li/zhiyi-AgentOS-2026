# 意图理解前导模型：论文库与阅读索引

[阅读中文综述](SUMMARY.md) · [全部研究总览](../RESEARCH_OVERVIEW.md)

整理日期：2026-11-18。共 14 份有效 PDF，227 页；发现记录 52 条。

## 研究范围与方法

采用 arXiv 主题检索与经典/直接相关工作的精确 ID 补查，选入与 Kinlin 项目接口、威胁模型和评估有关的材料。基础专著通过作者公开站点下载。

主题查询每组最多返回 45 条，按相关性排序；查询、返回总数和原始条目见 citations/search-results.json，所选 arXiv 元数据见 citations/selected-metadata.xml。Intent 主题沿用端云主题检索中的独立 intent_clarification 查询，已复制到本目录。

检索有关键词、排序和返回上限，不是全球穷尽检索。已选材料进行了人工相关性选择；未选条目的初始标记为粗筛，不能解释为每条均已独立精读或确定无关。评分表示本次阅读优先级，不是论文质量排名。

已验证 PDF 签名、全部页面对象、页数、文本抽取和 SHA-256。全文可用不等于逐页精读；方法选读页码记录在 citations/reading-log.json。未运行论文模型或下载的代码。

arXiv 年份按提交信息记录，正式发表信息以出版方为准；2026 年预印本不能自动视为同行评审结论。

## 全文清单

| # | 简称/ID | 论文标题与来源 | 本地全文 | 页数 | 阅读深度 |
|---|---|---|---|---:|---|
| 1 | CLINC150-Out-of-Scope<br>1909.02027v1 | [An Evaluation Dataset for Intent Classification and Out-of-Scope Prediction](https://arxiv.org/abs/1909.02027v1) | [PDF](1909.02027_CLINC150-Out-of-Scope.pdf) | 6 | 摘要筛选；已下载全文 |
| 2 | Schema-Guided-Dialogue<br>1909.05855v2 | [Towards Scalable Multi-domain Conversational Agents: The Schema-Guided Dialogue Dataset](https://arxiv.org/abs/1909.05855v2) | [PDF](1909.05855_Schema-Guided-Dialogue.pdf) | 11 | 摘要与方法选读 |
| 3 | PICARD<br>2109.05093v1 | [PICARD: Parsing Incrementally for Constrained Auto-Regressive Decoding from Language Models](https://arxiv.org/abs/2109.05093v1) | [PDF](2109.05093_PICARD.pdf) | 7 | 摘要与方法选读 |
| 4 | CLAM-Selective-Clarification<br>2212.07769v2 | [CLAM: Selective Clarification for Ambiguous Questions with Generative Language Models](https://arxiv.org/abs/2212.07769v2) | [PDF](2212.07769_CLAM-Selective-Clarification.pdf) | 17 | 摘要与方法选读 |
| 5 | FrugalGPT<br>2305.05176v1 | [FrugalGPT: How to Use Large Language Models While Reducing Cost and Improving Performance](https://arxiv.org/abs/2305.05176v1) | [PDF](2305.05176_FrugalGPT.pdf) | 13 | 摘要筛选；已下载全文 |
| 6 | CLAMBER<br>2405.12063v2 | [CLAMBER: A Benchmark of Identifying and Clarifying Ambiguous Information Needs in Large Language Models](https://arxiv.org/abs/2405.12063v2) | [PDF](2405.12063_CLAMBER.pdf) | 21 | 摘要与方法选读 |
| 7 | RouteLLM<br>2406.18665v4 | [RouteLLM: Learning to Route LLMs with Preference Data](https://arxiv.org/abs/2406.18665v4) | [PDF](2406.18665_RouteLLM.pdf) | 16 | 摘要与方法选读 |
| 8 | IntentGPT<br>2411.10670v1 | [IntentGPT: Few-shot Intent Discovery with Large Language Models](https://arxiv.org/abs/2411.10670v1) | [PDF](2411.10670_IntentGPT.pdf) | 24 | 摘要与方法选读 |
| 9 | AskToAct<br>2503.01940v2 | [AskToAct: Enhancing LLMs Tool Use via Self-Correcting Clarification](https://arxiv.org/abs/2503.01940v2) | [PDF](2503.01940_AskToAct.pdf) | 27 | 摘要筛选；已下载全文 |
| 10 | ECLAIR<br>2503.20791v1 | [ECLAIR: Enhanced Clarification for Interactive Responses in an Enterprise AI Assistant](https://arxiv.org/abs/2503.20791v1) | [PDF](2503.20791_ECLAIR.pdf) | 3 | 摘要筛选；已下载全文 |
| 11 | AskBench<br>2602.11199v2 | [When and What to Ask: AskBench and Rubric-Guided RLVR for LLM Clarification](https://arxiv.org/abs/2602.11199v2) | [PDF](2602.11199_AskBench.pdf) | 21 | 摘要与方法选读 |
| 12 | Ask-or-Assume<br>2603.26233v3 | [Ask or Assume? Uncertainty-Aware Clarification-Seeking in Coding Agents](https://arxiv.org/abs/2603.26233v3) | [PDF](2603.26233_Ask-or-Assume.pdf) | 19 | 摘要筛选；已下载全文 |
| 13 | Underspecified-Tabular-QA<br>2604.10159v2 | [ODUTQA-MDC: A Task for Open-Domain Underspecified Tabular QA with Multi-turn Dialogue-based Clarification](https://arxiv.org/abs/2604.10159v2) | [PDF](2604.10159_Underspecified-Tabular-QA.pdf) | 22 | 摘要筛选；已下载全文 |
| 14 | Information-Gain-Clarification<br>2606.03135v1 | [Uncertainty-Aware Clarification in LLM Agents with Information Gain](https://arxiv.org/abs/2606.03135v1) | [PDF](2606.03135_Information-Gain-Clarification.pdf) | 20 | 摘要筛选；已下载全文 |

## 文件说明

- SUMMARY.md：中文研究文章，区分论文结论、项目现状与设计建议。
- papers-reviewed.json：发现记录、选择状态、版本和摘要；未选不等于全文已审查。
- relevant-papers.json：本目录已选全文子集，含来源、页数、SHA-256 和阅读深度。
- citations/：原始检索和所选元数据、方法选读日志；没有宣称完成全量引用网络。
- text/：PDF 文本抽取；公式与版式以原 PDF 为准。
- ../planner/scripts/finalize_additional_topics.py：本地校验和索引生成脚本；不会覆盖综述。
