from pathlib import Path
import json, hashlib, re
import fitz
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'papers-reviewed.json'; records=json.loads(p.read_text(encoding='utf-8'))
for key,title,slug in [
 ('MACT','Efficient Multi-Agent Collaboration with Tool Use for Online Planning in Complex Table Question Answering','2025.findings-naacl.54'),
 ('Table-Critic','Table-Critic: A Multi-Agent Framework for Collaborative Criticism and Refinement in Table Reasoning','2025.acl-long.853'),
 ('TALON','TALON: A Multi-Agent Framework for Long-Table Exploration and Question Answering','2025.emnlp-main.1393')]:
 records[key].update(title=title,url=f'https://aclanthology.org/{slug}/')
method={'Binder','Dater','ReAcTable','Chain-of-Table','TabSQLify','TableRAG','ST-Raptor','AutoTQA','TaPERA','EviDARL','SkillTGR','QUIETT','TabClaw','Data-Readme'}
for value in records.values():
 if value.get('short_name') in method:value['reading_level']='full_text_method_excerpt_plus_abstract'
 if value.get('file'):
  f=ROOT/value['file'];d=fitz.open(f)
  assert len(d)==value['pages']
  assert hashlib.sha256(f.read_bytes()).hexdigest()==value['sha256']
  value['pdf_verified']='signature_open_pages_sha256'
p.write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
relevant={k:v for k,v in records.items() if v['score']>=7}
(ROOT/'relevant-papers.json').write_text(json.dumps(relevant,ensure_ascii=False,indent=2),encoding='utf-8')
order=['2506.05813','MACT','Table-Critic','TALON','2603.09151']
ordered=[relevant[k] for k in order]+sorted([v for k,v in relevant.items() if k not in order],key=lambda v:v.get('published',v['id']))
lines=['# Planner 论文库与阅读索引','',
 '[阅读中文综述：从表格问答到经验驱动的自适应规划](SUMMARY.md)','',
 '新增专题：[差分隐私](../differential_privacy/SUMMARY.md) · [本地前导网络](../leading_model/SUMMARY.md) · [意图理解前导模型](../intent_model/SUMMARY.md) · [全部研究总览](../RESEARCH_OVERVIEW.md)','',
 f'整理日期：2026-11-18。共 {len(relevant)} 份有效 PDF：原有种子论文 5 份，新增下载 39 份；合计 {sum(v["pages"] for v in relevant.values())} 页。ST-Raptor 包含方法论文与系统短文两个版本。','',
 '## 阅读顺序','',
 '先阅读 MACT 与 TALON，理解规划、执行与数据访问；再阅读 Table-Critic 与 MAPLE，理解局部修复和经验归档；最后阅读 DTR 与 ST-Raptor，理解层级表结构与路径选择。实现细节和项目接入建议均在 SUMMARY.md 中。','',
 '## 全文清单','',
 '| # | 简称 | 论文标题与来源 | 本地 PDF | 页数 | 阅读深度 |','|---|---|---|---|---:|---|']
for i,v in enumerate(ordered,1):
 depth='重点阅读方法、实验及附录' if v['status']=='seed' else ('摘要与方法选读' if v.get('short_name') in method else '摘要筛选；已下载全文')
 lines.append(f'| {i} | {v["short_name"]} | [{v["title"]}]({v["url"]}) | [PDF]({v["file"]}) | {v["pages"]} | {depth} |')
lines+=['','## 检索与筛选','',
 f'- 去重记录 {len(records)} 条，已选下载 {len(relevant)} 份（含 5 份种子）；“可能扩展”不等于全文已读。',
 '- 使用 arXiv 四组查询，每组最多 60 条；按提交时间排序。基础查询漏掉的经典工作用精确 ID 补查。ACL/VLDB 的两篇补充通过出版来源下载。',
 '- 宽泛词匹配存在无关结果。已人工选择本次重点，其他记录的初筛状态为启发式标记，不宣称 185 条均经过独立人工摘要审查。',
 '- 原始查询、结果元数据和时间保存在 citations/search-results.json 及对应 XML。检索不是全球穷尽搜索。',
 '- 评分只表示本主题优先级；新增精选一般为 8/10，直接核心补充为 9/10，用户种子为 10/10。',
 '- 验证了每个 PDF 的签名、可打开性、页数和 SHA-256；没有运行论文模型或执行下载的外部脚本。','',
 '## 文件与复现','',
 '- SUMMARY.md：中文研究文章，含方法对比、实验口径、实现建议、项目接口映射和验证计划。',
 '- papers-reviewed.json：全部发现记录、来源、下载状态、版本、阅读深度和校验摘要。',
 '- relevant-papers.json：44 份已收录材料的结构化子集。',
 '- citations/citation-graph.json：从种子全文名称匹配提取的候选引用关系；不能视为逐条核实的完整引用图，未完成全量前向引用遍历。',
 '- citations/：原始检索响应、公开 README 和实际读取的源文件文本快照。',
 '- text/：PDF 抽取文本与种子方法图检查图；供定位，版式与公式以 PDF 为准。',
 '- scripts/retrieve_literature.py：重做检索或按现有清单补齐下载；scripts/finalize_catalog.py：验证和生成索引。',
 '- build_catalog.py 会重建初始清单；再次运行前应保存已有人工阅读标记，避免覆盖。','',
 '新增论文按检索时的 arXiv 版本记录；清单中的预印本不自动等同于正式录用版本。代码仓库只核查了文中说明的入口，未完成运行复现。']
(ROOT/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
# Name matching yields candidate mentions, not a verified citation network.
names={'2210.02875':['binder'],'2301.13808':['dater'],'2310.00815':['reactable'],'2401.04398':['chain-of-table','chain of table'],'2410.04739':['tablerag'],'2303.11366':['reflexion'],'2308.10144':['expel'],'2502.12110':['a-mem'],'2506.13405':['realhitbench'],'2508.18190':['st-raptor'],'2402.02716':['understanding the planning'],'10.18653/v1/2024.acl-long.692':['tapera'],'10.14778/3685800.3685816':['autotqa'],'Table-Critic':['table-critic']}
graph={}
for key in order:
 seed=records[key];text=(ROOT/'text'/(Path(seed['file']).stem+'.txt')).read_text(encoding='utf-8').lower()
 refs=[target for target,aliases in names.items() if target!=key and any(a in text for a in aliases)]
 graph[key]={'title':seed['title'],'references':refs,'cited_by':[], 'evidence':'Candidate name mention in seed full text; automated alias match, not independently verified citation edges.', 'forward_citation_status':'not_completed; public Semantic Scholar lookup unavailable/rate-limited'}
(ROOT/'citations/citation-graph.json').write_text(json.dumps(graph,ensure_ascii=False,indent=2),encoding='utf-8')
print('Verified',len(relevant),'PDFs;',sum(v['pages'] for v in relevant.values()),'pages; generated README, relevant subset and limited citation graph.')
