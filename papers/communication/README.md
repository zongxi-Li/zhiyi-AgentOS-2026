# 通信器学术研究

更新：2026-11-25。当前阶段：专题文献综述与问题诊断，尚未开展论文模型实验。

用户目标：结合项目完善，先完成一篇扎实的方法或系统论文。

建议按以下顺序阅读：

1. [文献综述](SUMMARY.md)：六条研究线索、最近邻与选题修正。
2. [问题调研](PROBLEM_STUDY.md)：项目基础、候选问题、假设和最小诊断实验。
3. [文献矩阵](LITERATURE_MATRIX.md)：38篇文献的设计与比较维度。
4. [文献目录](REFERENCES.md)与[阅读记录](READING_LOG.md)：原始来源、版本和实际阅读深度。
5. [检索记录](SEARCH_LOG.md)与[语料内引用](citations/CITATION_GRAPH.md)：方法、范围与可追溯性。

[2026-11-24初步研究计划](RESEARCH_PLAN.md)保留为历史起点。2026-11-25调研已经找到AOD、MSS-Complement、SCH等强近邻，不能继续将泛化的“按需读取”视作尚未被研究的创新点；选题判断以本轮综述和问题调研为准。

## 本轮范围

主语料核对38篇文献的标题、作者、日期与摘要，18篇定向选读正文，20篇仅摘要筛选；另补充3篇边界文献的摘要与1篇流程工具来源。确认66条主语料内引用关系。没有完成穷尽检索、双人筛选、完整前向引文追踪或论文复现。

## 可复查文件

- `scripts/collect_review_sources.py`：有界候选语料、标题匹配核验、原始元数据与HTML取回。
- `scripts/build_review_catalog.py`：人工筛选注释、目录／矩阵／阅读日志和引用关系生成。
- `papers-reviewed.json`、`relevant-papers.json`、`citations/citation-graph.json`：本地结构化记录。
- `.build/sources/`：本地原始HTML与提取正文，不是随仓交付物。

沿用仓库`.gitignore`：研究JSON和下载正文留在本地；Markdown和Python源文件可进入Git。因此核心结论、38篇元数据目录、筛选理由与引用关系均另有Markdown版本，不依赖下载缓存才能阅读。

在仓库根目录运行元数据核查与目录生成：

```powershell
python papers/communication/scripts/collect_review_sources.py --full P01,P03,P04,P05,P06,P07,P08,P09,P11,P19,P20,P21,P22,P23,P25,P30,P37,P38
python papers/communication/scripts/build_review_catalog.py
```

脚本默认复用本地缓存，传入`--refresh`可重新取回有界语料；不会自动重做人工选读和问题判断。`review_date`保留本轮综述日期，`checked_at_utc`记录脚本检查时间，后续刷新应人工复查版本并更新综述。首次运行需要`requests`和`beautifulsoup4`，网络限流可能使取回失败；标题不匹配时脚本保留失败并以非零退出码结束，避免把错误文献纳入目录。
