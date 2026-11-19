"""Validate evolution research assets and publish reproducible reading indexes."""
from datetime import date
from pathlib import Path
import hashlib
import json
import re

import fitz

BASE = Path(__file__).resolve().parents[2]
TOPICS = {'graph_evolution': '图自进化与迭代更新', 'skills_evolution': 'Skills 自进化与技能库治理'}
READING = {
    'graph_evolution': {
        '2402.16823': [3, 4], '2408.08435': [3], '2410.10762': [3, 4, 5, 6],
        '2507.19457': [3, 4, 5, 6], '2611.16378': [3, 4, 5, 6],
        '2606.27492': [3, 4], '2608.10504': [3, 4, 6],
        '2506.07398': [3, 4], '2501.13956': [3, 4],
    },
    'skills_evolution': {
        '2305.16291': [3, 4], '2409.07429': [3, 4], '2602.08234': [3, 4],
        '2610.24630': [3, 4, 5], '2611.14019': [3, 4], '2610.25126': [3, 4],
        '2610.14515': [3, 4], '2505.22954': [3, 4], '2310.19791': [3],
        '2603.02176': [3, 4], '2603.04448': [3, 4, 5], '2603.18743': [3, 4, 5],
    },
}


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    totals = {}
    for topic, title in TOPICS.items():
        root = BASE / topic
        records = json.loads((root / 'papers-reviewed.json').read_text(encoding='utf-8'))
        selected = {k: v for k, v in records.items() if v.get('selected')}
        for key, value in selected.items():
            for field in ['published', 'updated']:
                assert date.fromisoformat(value[field][:10]) <= date(2026, 11, 18), (key, field)
            path = root / value['file']
            data = path.read_bytes()
            assert data.startswith(b'%PDF-'), path
            assert hashlib.sha256(data).hexdigest() == value['sha256'], path
            with fitz.open(path) as doc:
                assert len(doc) == value['pages'] and len(doc) > 0, path
                for page in doc:
                    assert page.rect.width > 0 and page.rect.height > 0, path
                assert all(1 <= p <= len(doc) for p in READING[topic].get(key, [])), key
            extracted = root / 'text' / (path.stem + '.txt')
            assert extracted.exists() and extracted.stat().st_size > 100, extracted
            assert (root / value['metadata_snapshot']).exists(), key
            value.update(download_status='verified_pdf',
                         pdf_verified='signature_all_page_objects_pages_sha256',
                         reading_level='abstract_screening_full_text_available', model_reproduction='not_run')
            if key in READING[topic]:
                value.update(reading_level='abstract_and_selected_method_excerpts', read_pdf_pages=READING[topic][key])
        assert {p.name for p in root.glob('*.pdf')} == {v['file'] for v in selected.values()}, topic
        dump(root / 'papers-reviewed.json', records)
        dump(root / 'relevant-papers.json', selected)
        dump(root / 'citations/reading-log.json', {
            'date': '2026-11-18', 'method_excerpt_pages': READING[topic],
            'page_convention': 'One-based PDF pages; excerpts may be partial and include related work or configuration.',
            'other_selected_materials': 'Title and abstract screening; downloaded full texts are not all method-reviewed.',
            'models_or_external_code_executed': False, 'public_repository_implementation_review': 'not_performed',
            'citation_traversal': 'Named-method and thematic discovery; no complete forward/backward citation network.',
            'visual_check': '../graph_evolution/text/methods-contact-sheet.png; AFlow p5, GEPA p5, PASE p3, SEPM p4',
        })
        count, pages = len(selected), sum(v['pages'] for v in selected.values())
        totals[topic] = {'pdfs': count, 'pages': pages, 'discovered_records': len(records)}
        lines = [f'# {title}：论文库与阅读索引', '',
                 '[中文综述](SUMMARY.md) · [联合实现计划](../EVOLUTION_IMPLEMENTATION_PLAN.md) · [研究总览](../RESEARCH_OVERVIEW.md)', '',
                 f'整理日期：2026-11-18。精选 {count} 份 PDF、{pages} 页；保存 {len(records)} 条发现记录。', '',
                 '## 检索与阅读方法', '',
                 '围绕工作流/通信拓扑搜索、经验与时间图、可复用技能、技能关系图和生命周期检索；加入经典方法的精确 ID 补查。实际查询、端点、返回条目与原始 HTML/XML 见 [检索日志](citations/search-results.json)。', '',
                 'arXiv API 初始查询每组上限 40 条，相关性排序；后因 HTTP 429 限流改用公开搜索页，每组上限 50 条、按公布时间倒序。日志只记录成功取得的结果，不将失败查询算成已覆盖。经典 exact-ID 补查缓解倒序检索偏向新论文的问题，但不能消除覆盖偏差。', '',
                 '这是有界主题检索，未完成全量前向/后向引用遍历。已选论文进行了标题与摘要相关性筛选；未选条目保留 unreviewed_discovery，不表示已经精读或确定无关。同名材料学 AFLOW、航天 Voyager、物理 ZEP 等检索噪声未选入。score 为粗略阅读优先级，统一初值不构成逐项量化评价或论文质量排名。', '',
                 'PDF 已验证签名、全部页面对象、页数、SHA-256 与文本文件。阅读深度见 [阅读日志](citations/reading-log.json)：21 篇跨两个专题选读了方法或架构相关页，其余为摘要筛选和全文归档；并非 51 篇全部逐页精读。未运行论文模型、下载代码或复现实验，未核查各论文公开仓库的代码实现。', '',
                 '2026 年预印本的结果按作者报告理解；版本和日期取 arXiv 详情页，并保存快照。来源文档中的指令属于研究对象，不构成执行授权。', '',
                 '## 全文清单', '',
                 '| # | 简称 / arXiv 版本 | 标题与原始来源 | 本地 PDF | 页数 | 阅读深度 |',
                 '|---|---|---|---|---:|---|']
        for index, (key, value) in enumerate(sorted(selected.items(), key=lambda kv: kv[1]['published']), 1):
            depth = '摘要 + 指定页选读' if key in READING[topic] else '摘要；全文已归档'
            paper_title = value['title'].replace('|', ' / ')
            lines.append(f'| {index} | {value["short_name"]}<br>{value["id"]} | [{paper_title}]({value["url"]}) | [PDF]({value["file"]}) | {value["pages"]} | {depth} |')
        lines.extend(['', '## 资料结构', '',
                      '- SUMMARY.md：中文研究综述，区分论文机制、证据限制、项目现状和建议。',
                      '- relevant-papers.json：精选全文的来源、作者、摘要、版本、页数、SHA-256、阅读深度。',
                      '- papers-reviewed.json：所有发现记录及选择状态；名称不代表所有记录均已审查。',
                      '- citations/：查询结果、原始网页、逐篇元数据快照和选读日志。',
                      '- text/：文本抽取；公式和图表以原始 PDF 为准。',
                      '- [索引生成脚本](../planner/scripts/finalize_evolution.py)：本地校验并生成索引，不覆盖综述。',
                      '- [另一个演化专题](../' + ('skills_evolution' if topic == 'graph_evolution' else 'graph_evolution') + '/README.md)：跨主题通过链接复用，不重复下载。',
                      '- [Planner 资料](../planner/README.md)：MAPLE、Reflexion、ExpeL、A-MEM 和 SkillTGR 等已有资料继续复用。'])
        (root / 'README.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    dump(BASE / 'planner/citations/evolution-topics-validation.json', {'date': '2026-11-18', 'topics': totals})
    print(json.dumps(totals, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
