# 差分隐私：论文库与阅读索引

[阅读中文综述](SUMMARY.md) · [全部研究总览](../RESEARCH_OVERVIEW.md)

整理日期：2026-11-18。共 18 份有效 PDF，602 页；发现记录 112 条。

## 研究范围与方法

采用 arXiv 主题检索与经典/直接相关工作的精确 ID 补查，选入与 Kinlin 项目接口、威胁模型和评估有关的材料。基础专著通过作者公开站点下载。

主题查询每组最多返回 45 条，按相关性排序；查询、返回总数和原始条目见 citations/search-results.json，所选 arXiv 元数据见 citations/selected-metadata.xml。Intent 主题沿用端云主题检索中的独立 intent_clarification 查询，已复制到本目录。

检索有关键词、排序和返回上限，不是全球穷尽检索。已选材料进行了人工相关性选择；未选条目的初始标记为粗筛，不能解释为每条均已独立精读或确定无关。评分表示本次阅读优先级，不是论文质量排名。

已验证 PDF 签名、全部页面对象、页数、文本抽取和 SHA-256。全文可用不等于逐页精读；方法选读页码记录在 citations/reading-log.json。未运行论文模型或下载的代码。

arXiv 年份按提交信息记录，正式发表信息以出版方为准；2026 年预印本不能自动视为同行评审结论。

## 全文清单

| # | 简称/ID | 论文标题与来源 | 本地全文 | 页数 | 阅读深度 |
|---|---|---|---|---:|---|
| 1 | DP-Foundations-Book<br>Dwork-Roth-2014 | [The Algorithmic Foundations of Differential Privacy](https://www.cis.upenn.edu/~aaroth/privacybook.html) | [PDF](2014_Dwork-Roth_Algorithmic-Foundations-DP.pdf) | 281 | 摘要与方法选读 |
| 2 | Privacy-Odometers-Filters<br>1605.08294v3 | [Privacy Odometers and Filters: Pay-as-you-Go Composition](https://arxiv.org/abs/1605.08294v3) | [PDF](1605.08294_Privacy-Odometers-Filters.pdf) | 21 | 摘要筛选；已下载全文 |
| 3 | DP-SGD<br>1607.00133v2 | [Deep Learning with Differential Privacy](https://arxiv.org/abs/1607.00133v2) | [PDF](1607.00133_DP-SGD.pdf) | 14 | 摘要筛选；已下载全文 |
| 4 | Renyi-DP<br>1702.07476v3 | [Renyi Differential Privacy](https://arxiv.org/abs/1702.07476v3) | [PDF](1702.07476_Renyi-DP.pdf) | 13 | 摘要与方法选读 |
| 5 | Analytic-Gaussian<br>1805.06530v2 | [Improving the Gaussian Mechanism for Differential Privacy: Analytical Calibration and Optimal Denoising](https://arxiv.org/abs/1805.06530v2) | [PDF](1805.06530_Analytic-Gaussian.pdf) | 23 | 摘要与方法选读 |
| 6 | Subsampled-RDP-Accountant<br>1808.00087v2 | [Subsampled Rényi Differential Privacy and Analytical Moments Accountant](https://arxiv.org/abs/1808.00087v2) | [PDF](1808.00087_Subsampled-RDP-Accountant.pdf) | 29 | 摘要筛选；已下载全文 |
| 7 | Sampled-Gaussian-RDP<br>1908.10530v1 | [Rényi Differential Privacy of the Sampled Gaussian Mechanism](https://arxiv.org/abs/1908.10530v1) | [PDF](1908.10530_Sampled-Gaussian-RDP.pdf) | 14 | 摘要筛选；已下载全文 |
| 8 | Numerical-Composition<br>2106.02848v3 | [Numerical Composition of Differential Privacy](https://arxiv.org/abs/2106.02848v3) | [PDF](2106.02848_Numerical-Composition.pdf) | 26 | 摘要与方法选读 |
| 9 | Feature-Space-Hijacking-DP<br>2201.04018v2 | [Feature Space Hijacking Attacks against Differentially Private Split Learning](https://arxiv.org/abs/2201.04018v2) | [PDF](2201.04018_Feature-Space-Hijacking-DP.pdf) | 11 | 摘要筛选；已下载全文 |
| 10 | Split-and-Denoise<br>2310.09130v4 | [Split-and-Denoise: Protect large language model inference with local differential privacy](https://arxiv.org/abs/2310.09130v4) | [PDF](2310.09130_Split-and-Denoise.pdf) | 22 | 摘要与方法选读 |
| 11 | Local-DP-ICL<br>2405.04032v2 | [Locally Differentially Private In-Context Learning](https://arxiv.org/abs/2405.04032v2) | [PDF](2405.04032_Local-DP-ICL.pdf) | 21 | 摘要筛选；已下载全文 |
| 12 | DP-LM-Scaling-Laws<br>2501.18914v1 | [Scaling Laws for Differentially Private Language Models](https://arxiv.org/abs/2501.18914v1) | [PDF](2501.18914_DP-LM-Scaling-Laws.pdf) | 23 | 摘要筛选；已下载全文 |
| 13 | Metric-DP-Calibration<br>2503.13872v1 | [Empirical Calibration and Metric Differential Privacy in Language Models](https://arxiv.org/abs/2503.13872v1) | [PDF](2503.13872_Metric-DP-Calibration.pdf) | 16 | 摘要筛选；已下载全文 |
| 14 | DP-Split-Stochastic-Quantization<br>2602.11513v1 | [Differentially Private and Communication Efficient Large Language Model Split Inference via Stochastic Quantization and Soft Prompt](https://arxiv.org/abs/2602.11513v1) | [PDF](2602.11513_DP-Split-Stochastic-Quantization.pdf) | 18 | 摘要与方法选读 |
| 15 | DP-RAG<br>2602.14374v1 | [Differentially Private Retrieval-Augmented Generation](https://arxiv.org/abs/2602.14374v1) | [PDF](2602.14374_DP-RAG.pdf) | 15 | 摘要筛选；已下载全文 |
| 16 | Guarding-the-Middle<br>2602.17614v1 | [Guarding the Middle: Protecting Intermediate Representations in Federated Split Learning](https://arxiv.org/abs/2602.17614v1) | [PDF](2602.17614_Guarding-the-Middle.pdf) | 10 | 摘要筛选；已下载全文 |
| 17 | DP-Training-Intermediate-Representations<br>2602.22611v2 | [Mitigating Membership Inference in Intermediate Representations with Differentially Private Training](https://arxiv.org/abs/2602.22611v2) | [PDF](2602.22611_DP-Training-Intermediate-Representations.pdf) | 19 | 摘要筛选；已下载全文 |
| 18 | Character-Level-DP-Prompts<br>2603.26032v1 | [Protecting User Prompts Via Character-Level Differential Privacy](https://arxiv.org/abs/2603.26032v1) | [PDF](2603.26032_Character-Level-DP-Prompts.pdf) | 26 | 摘要筛选；已下载全文 |

## 文件说明

- SUMMARY.md：中文研究文章，区分论文结论、项目现状与设计建议。
- papers-reviewed.json：发现记录、选择状态、版本和摘要；未选不等于全文已审查。
- relevant-papers.json：本目录已选全文子集，含来源、页数、SHA-256 和阅读深度。
- citations/：原始检索和所选元数据、方法选读日志；没有宣称完成全量引用网络。
- text/：PDF 文本抽取；公式与版式以原 PDF 为准。
- ../planner/scripts/finalize_additional_topics.py：本地校验和索引生成脚本；不会覆盖综述。
