"""Render the human-screened catalogue; do not interpret scores as study quality.

Requires collect_review_sources.py to have populated local papers-reviewed.json.
The Markdown outputs preserve the useful record under the repository's ignore policy.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
# Relevance = topic (0-3) + usable method/evaluation (0-4) + project specificity (0-3).
# Selection priority is a human judgment, not a calibrated probability or quality score.
# id: score, priority, control/unit, training, evidence recovery, benchmarks, project implication.
ANNOTATIONS = {
    "P01": (9, "强结构基线", "发送关系；时空边", "优化图掩码", "边剪枝，不以补读为核心", "MMLU、GSM8K等；HumanEval", "固定图的读取策略与图稀疏化应分开控制"),
    "P02": (8, "结构背景", "Agent与通信轮次", "摘要描述图优化", "摘要未详述", "摘要报告token与任务性能", "动态删Agent不能直接充当字段选择的等价方法"),
    "P03": (10, "最近邻", "请求方；请求、peer、历史片段", "训练0.6B帮助请求门控", "peer基于历史作答并引用原文", "AppWorld、WebShop", "按需提问、缺口表达和效用门控已有直接研究"),
    "P04": (9, "最近邻", "写入控制；摘要键和原始输出", "RL记忆准入控制器", "按键选择并注入原输出", "GAIA、AssistantBench", "目录轻量暴露加原文按需读取已经存在"),
    "P05": (9, "最近邻", "共享hub；episode与意图读取", "hub的SFT与RL", "保留原episode供深入读取", "长时程工具任务；方法部分选读", "不能宣称共享摘要一定使原文不可恢复"),
    "P06": (10, "最近邻／强基线", "发送投影；Action-State-Result", "协议本身不训练压缩器", "结构化证据交接；非通用分页接口", "拆分证据QA、推理、SWE-bench", "来源和行动状态结构化本身不足以成为创新"),
    "P07": (10, "最近邻／强基线", "接收状态；缺失证据集合", "三次语义调用；另有检索器", "交付完整代码单元和来源", "SERBench、AMA-Bench及修复诊断", "缺口驱动、集合充分性和原文完整性均已被研究"),
    "P08": (10, "最近邻／强基线", "确定性控制；语义状态、原证据", "无额外摘要或检索模型调用", "revision触发原证据恢复", "SWE-bench、AppWorld", "状态／证据分离与修订后恢复均有高度重合"),
    "P09": (9, "停止策略近邻", "持久证据状态；检索／验证／停止", "答案可答性校准与固定生成器", "证据workspace可增可删", "六个QA基准；方法选读", "缺口、冲突、新颖性与成本驱动停止不是空白"),
    "P10": (8, "基础背景", "分层内存与上下文移动", "摘要未作充分区分", "上下文外存储与调入", "文档分析、跨会话对话", "外置正文加按需访问有明确先例"),
    "P11": (9, "上下文强基线", "程序环境；切片、变量、递归调用", "提示实例；另有后训练实例", "原输入留在环境中供程序处理", "S-NIAH、BrowseComp+、OOLONG等", "一般化代码读上下文必须纳入对照思路"),
    "P12": (7, "基础背景", "交替推理与工具行动", "提示及论文其他设定", "经工具获得外部观察", "HotpotQA、FEVER、ALFWorld、WebShop", "会调用读取工具不是独立贡献"),
    "P13": (8, "检索基线", "接收推理状态；迭代检索", "摘要包含不额外训练设定", "随推理取回新段落", "HotpotQA、MuSiQue等", "下一次读什么取决于已知内容的论点已有先例"),
    "P14": (8, "检索基线", "生成侧；前瞻句子与检索", "摘要未详述训练", "低置信生成触发检索", "四类长文本生成任务", "按需决定何时和读什么已有成熟前身"),
    "P15": (8, "检索背景", "检索／反思token控制", "训练检索反思生成模型", "按需检索及支持反思", "QA、验证、长文生成", "需区分推理期策略与训练型方法"),
    "P16": (8, "路由基线", "问题复杂度；无／单步／迭代检索", "小模型分类器", "按查询选择检索策略", "不同复杂度开放域QA", "路由与逐步证据获取是不同层级"),
    "P17": (7, "压缩背景", "提示；粗到细token压缩", "含对齐训练", "压缩后不以通用原文恢复为核心", "GSM8K、BBH、ShareGPT、arXiv", "不能预设文本压缩必然更差"),
    "P18": (8, "压缩背景", "问题感知长提示压缩", "摘要未详述全部组件", "原文恢复非摘要所述核心", "NaturalQuestions、LooGLE等", "查询感知筛选和长上下文位置效应应控制"),
    "P19": (7, "系统边界", "同构模型；跨前缀KV复用", "训练免费；在线anchor", "不是字段级文本恢复问题", "RAG、数学、协作编码", "主要减少prefill；不可把TTFT收益等同总成本"),
    "P20": (7, "系统边界", "同基座模型；选择KV层", "选择策略校准", "交换KV，非审计文本单元", "多任务和模型对", "与P19同名但不同论文和实现"),
    "P21": (7, "潜空间边界", "多发送者；固定潜槽", "两阶段压缩器训练", "目标是接收任务效用", "Qwen3-4B多基准", "潜槽预算与API文本token、字节量分别比较"),
    "P22": (10, "关键评测依据", "分布信息；不同协议与Agent数", "基准非训练方法", "信息收集与合成分开诊断", "30类算法任务", "拿到足够数据仍可能整合错误"),
    "P23": (9, "失败分类依据", "系统、协同、验证失败轨迹", "含LLM标注流程", "不是读取算法", "MAST-Data；多系统轨迹", "错误归因需跨信息丢失、协同与验证"),
    "P24": (8, "泛化风险依据", "自适应MAS迁移与内部协同", "摘要层分析", "不以读取接口为核心", "摘要描述跨域实证", "最终答对不代表有效协同；避免拓扑过拟合"),
    "P25": (10, "关键评测依据", "压缩对象、触发、强度", "实证控制研究", "因策略而异", "SWE-bench、Terminal-Bench；三模型", "token下降不能替代实际时延、计费与成功率"),
    "P26": (9, "证据指标依据", "答案断言与引用支持", "评测框架与多种方法", "区分答案、引用与支持", "ALCE", "引用格式正确与断言被支持需要分别测量"),
    "P27": (7, "上下文风险背景", "关键事实在长上下文中的位置", "实证研究", "提供全文仍可能用不好", "多文档QA、键值检索", "不能把全文视作完美语义上界"),
    "P28": (8, "任务候选", "多跳问答和支持句", "数据资源", "有支持事实标注", "HotpotQA", "必须额外构造并公开多Agent信息分配规则"),
    "P29": (9, "任务候选", "关联式2—4跳问答", "数据构建与评测", "含不可回答对照", "MuSiQue", "有助于减少简单单跳捷径；仍需无证据基线"),
    "P30": (9, "来源保真近邻", "声明及支持状态、来源、传递历史", "结构化交接实验", "保存来源不引入新事实", "FEVER NEI；五阶段管线", "保持原主张不等于事实变真；新预印本边界窄"),
    "P31": (8, "综述背景", "typed provenance与证据关系", "综述", "区分支持与执行影响", "摘要层；非复现实验", "读过、影响决策与语义支持是不同关系"),
    "P32": (8, "综述背景", "目标、机制、控制策略", "综述", "讨论压缩后访问失败", "摘要层；跨软件／网页／研究", "区分压缩前选错、压缩时丢失、之后读不到"),
    "P33": (6, "系统背景", "SOP角色和产物流转", "框架", "摘要未详述证据恢复", "软件工程", "仅做背景，不凭摘要比较细节"),
    "P34": (6, "系统背景", "可编程多Agent会话", "框架", "由应用定义", "多类工具与交互任务", "研究应独立于Kinlin名称和框架包装"),
    "P35": (5, "外围背景", "互操作协议分类", "综述", "不等价于按需证据获取", "协议分类与性能维度", "不作为候选读取策略的主要效果对手"),
    "P36": (5, "外围背景", "MCP／ACP／A2A／ANP", "综述", "标准互操作与部署", "协议对比", "本轮不审计这些协议的最新实现或规范"),
    "P37": (9, "决策保持近邻", "历史span；未来依赖选择", "无需训练；draft rollouts", "保留完整交互span", "方法与机制选读", "未来决策相关性并非尚未被提出的目标"),
    "P38": (7, "潜空间边界", "工具观察；连续latent", "动作分布保持蒸馏", "非文本精确恢复接口", "方法选读", "压缩目标已延伸到下一步动作，而非文本相似度"),
}

SECTION_NOTES = {
    "P01": "§3 时空边优化与one-shot pruning；§4.1 任务和模型。",
    "P03": "§3 请求need/known/decision、BM25 peer选择、门控训练；§4.1 设置；主结果表。",
    "P04": "§3.1 原始输出值与摘要键；§4.1 设置；§4.3 消融；§4.4 限制。",
    "P05": "§2.1—2.2 episode保存、意图读取与原episode深读；未逐表核验结果。",
    "P06": "§3 诊断；§4 消息空间；§5 表1—3；§6 表4及限制。",
    "P07": "§3—5 定义、SERBench和三调用方法；§6.1—6.4 成本与下游诊断。",
    "P08": "§3 状态、ack、证据归档、revision恢复；摘要结果与§6限制。",
    "P09": "§3 诊断、可答性校准和停止规则；未逐表核验实验。",
    "P11": "§2 REPL与符号递归；§3.1 任务；未逐表核验结果。",
    "P19": "§3.1 同构模型假设、prefill复用；§6.1限制；公开仓库链接。",
    "P20": "§3.1 KV交换接口；§6同基座限制和扩展；公开仓库链接。",
    "P21": "§3 两阶段潜槽训练；Limitations的异构模型与固定槽限制。",
    "P22": "§3 信息分片、任务生成和通信复杂度；§5.2失败与整合。",
    "P23": "§4 MAST三类与14模式；§5.1失败分布；摘要的数据范围。",
    "P25": "§3 控制变量、任务与模型；§4 Q1的token、计费及延迟区分。",
    "P30": "§III 数据／五阶段管线／NLI度量；§VI比较；未确认广泛外推。",
    "P37": "§4 span、draft计划依赖、defensive verification；未逐表核验结果。",
    "P38": "§3 工具观察潜表示与动作保持训练；未逐表核验结果。",
}


def norm(s): return re.sub(r"[^a-z0-9]", "", s.lower())


def main():
    path = ROOT / "papers-reviewed.json"
    records = json.loads(path.read_text(encoding="utf-8"))
    assert len(records) == 39 and len({r["id"] for r in records}) == 39
    assert all(r["status"] == "metadata_verified" and r["authors"] and r["abstract"] for r in records)
    matrix = ["# 通信器研究：文献比较矩阵", "", "检索截止：2026-11-25。38篇主题文献，另有1篇流程工具来源。", "",
              "本表的‘摘要筛选’只支持摘要明确陈述的判断；‘定向选读’指列出的正文部分，均不代表全文逐页精读或复现。NR或‘未详述’表示本轮未核查，不能解读为原论文没有该能力。相关性分数不代表论文质量。", "",
              "| ID | 文献／日期 | 定位 | 选择单位／控制点 | 训练或额外计算 | 原证据访问 | 已核查验证范围 | 阅读层级 |", "|---|---|---|---|---|---|---|---|"]
    refs = ["# 通信器研究：已核查文献目录", "", "截至2026-11-25。ID与综述、问题调研、矩阵对应。日期按源页元数据保留，arXiv日期通常是首次提交日期，版本说明另列。ACL记录按正式会议页标识；其余不因arXiv存档自行推断发表或录用状态。", ""]
    reading = ["# 阅读与筛选记录", "", "38篇主题文献均核对标题、作者、日期和摘要；18篇定向选读正文，其余20篇为摘要层。M01仅作为研究流程工具来源，不计入38篇。没有论文复现或独立效果确认。", "", "| ID | 相关性／10 | 用途 | 已读范围与筛选理由 |", "|---|---:|---|---|"]
    edges = []
    for r in records:
        pid = r["id"]
        if pid == "M01":
            r.update(score=0, decision="methodology_only", reading_depth="abstract", screening_reason="流程技能来源，不属于通信研究语料")
        else:
            score, priority, unit, training, recovery, benchmark, implication = ANNOTATIONS[pid]
            selected = pid in SECTION_NOTES
            r.update(score=score, decision="core_or_background" if score >= 7 else "background_only", reading_depth="targeted_fulltext" if selected else "abstract",
                     selected_sections=SECTION_NOTES.get(pid, "标题与摘要"), screening_reason=implication,
                     evidence_notes={"priority": priority, "unit": unit, "training_or_computation": training, "recovery": recovery, "evaluation_scope": benchmark})
            depth = "定向选读" if selected else "摘要筛选"
            matrix.append(f"| {pid} | [{r['alias']}]({r['url']})<br>{r['publication_date']} | {priority} | {unit} | {training} | {recovery} | {benchmark} | {depth} |")
            reading.append(f"| {pid} | {score} | {priority} | {r['selected_sections']} {implication}。 |")
        refs += [f'<a id="{pid.lower()}"></a>', "", f"## {pid} · {r['title']}", "", f"作者：{'; '.join(r['authors'])}。", "", f"日期：{r['publication_date']}。原始来源：[{r['url']}]({r['url']})。", ""]
        if r.get("version_note"): refs += [f"版本：{r['version_note']}。", ""]
        if r.get("doi"): refs += [f"DOI：[{r['doi']}](https://doi.org/{r['doi']})。", ""]
        if r.get("fulltext_retrieved"):
            refs += [f"正文HTML已取回；本轮选读范围：{SECTION_NOTES.get(pid, '未记录')}", ""]
            files = list((ROOT / ".build/sources").glob(pid+"-*-full.html"))
            soup = BeautifulSoup(files[-1].read_text(encoding="utf-8"), "html.parser")
            for target in records:
                if target['id']==pid: continue
                needle = norm(target["title"])
                for item in soup.select("li.ltx_bibitem"):
                    if needle in norm(item.get_text(" ", strip=True)):
                        edges.append({"from":pid,"to":target["id"],"relation":"cites","evidence_id":item.get("id"),"evidence_url":r["fulltext_url"]+"#"+item.get("id","")})
                        break
    supplement_path = ROOT / "supplementary-candidates.json"
    if supplement_path.exists():
        supplements = json.loads(supplement_path.read_text(encoding="utf-8"))
        refs += ["# 补充边界文献", "", "以下3篇在候选问题反向检索中补充，已核对元数据与摘要，未选读正文，不计入主矩阵38篇。", ""]
        for r in supplements:
            assert r["status"] == "metadata_verified"
            refs += [f'<a id="{r["id"].lower()}"></a>', "", f'## {r["id"]} · {r["title"]}', "",
                     f'作者：{"; ".join(r["authors"])}。', "", f'日期：{r["publication_date"]}。来源：[{r["url"]}]({r["url"]})。', "",
                     f'版本：{r.get("version_note", "未注明")}。阅读层级：摘要筛选。', ""]
    matrix += ["", "## 每篇文献对项目的直接含义", ""]
    matrix += [f"- **{pid}**：{v[-1]}。" for pid,v in ANNOTATIONS.items()]
    matrix += ["", "全部作者、版本与DOI见[文献目录](REFERENCES.md)；具体阅读位置见[阅读记录](READING_LOG.md)。"]
    (ROOT/"LITERATURE_MATRIX.md").write_text("\n".join(matrix)+"\n",encoding="utf-8")
    (ROOT/"REFERENCES.md").write_text("\n".join(refs),encoding="utf-8")
    (ROOT/"READING_LOG.md").write_text("\n".join(reading)+"\n",encoding="utf-8")
    path.write_text(json.dumps(records,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (ROOT/"relevant-papers.json").write_text(json.dumps([r for r in records if r["score"]>=7],ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (ROOT/"citations").mkdir(exist_ok=True)
    graph={"date":"2026-11-25","method":"Exact normalized title matching in retrieved bibliographies; curated corpus only; no exhaustive forward traversal", "edges":edges}
    (ROOT/"citations/citation-graph.json").write_text(json.dumps(graph,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    lines=["# 本轮确认的语料内引用关系", "", "从取回的正文参考文献中按规范化完整标题匹配。只表示已确认的引用，不代表语料外的完整引用网络，也不是系统性的前向被引统计。", "", f"共{len(edges)}条有出处的有向关系。", "", "| 引用方 | 被引方 | 源文参考文献锚点 |", "|---|---|---|"]
    lines += [f"| {e['from']} | {e['to']} | [{e['evidence_id']}]({e['evidence_url']}) |" for e in edges]
    (ROOT/"citations/CITATION_GRAPH.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print({"thematic_papers":len(ANNOTATIONS),"targeted_fulltext":len(SECTION_NOTES),"abstract_only":len(ANNOTATIONS)-len(SECTION_NOTES),"within_corpus_citation_edges":len(edges),"relevant_score_at_least_7":sum(r['score']>=7 for r in records)})


if __name__ == "__main__": main()
