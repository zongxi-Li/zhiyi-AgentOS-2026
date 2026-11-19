"""Validate collected PDFs and build transparent, topic-specific reading indexes.

Runs locally without a network or model calls. Does not overwrite SUMMARY.md.
"""
from pathlib import Path
import hashlib
import json
import re

import fitz

BASE = Path(__file__).resolve().parents[2]
TOPICS = {
    'differential_privacy': '差分隐私',
    'leading_model': '本地前导网络与端云拆分',
    'intent_model': '意图理解前导模型',
}
# PDF page numbers, not printed page numbers. These record excerpt reading,
# not a claim to have read every intervening page or reproduced the method.
READING = {
    'differential_privacy': {
        'Dwork-Roth-2014': [22, 23, 265],
        '1702.07476': [2, 3, 4, 6],
        '1805.06530': [3, 4],
        '2106.02848': [1, 3],
        '2310.09130': [1, 3, 4],
        '2602.11513': [1, 3, 4, 5],
    },
    'leading_model': {
        '2605.23158': [1, 3, 4],
        '2310.06816': [1, 3],
        '2602.16760': [1, 3],
        '2008.09161': [2, 3],
        '2511.13365': [3, 4],
        '2407.08977': [1, 4],
    },
    'intent_model': {
        '2411.10670': [1, 2, 3, 4],
        '2405.12063': [1, 3],
        '2602.11199': [1, 3, 4],
        '2109.05093': [2, 3],
        '2406.18665': [3, 4],
        '2212.07769': [3],
        '1909.05855': [3],
    },
}


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    leading_queries = json.loads((BASE / 'leading_model/citations/search-results.json').read_text(encoding='utf-8'))
    dump(BASE / 'intent_model/citations/search-results.json', {
        'intent_clarification': leading_queries['intent_clarification'],
    })
    totals = {}
    for topic, title in TOPICS.items():
        root = BASE / topic
        records = json.loads((root / 'papers-reviewed.json').read_text(encoding='utf-8'))
        if topic == 'differential_privacy':
            book = json.loads((root / 'citations/privacybook-metadata.json').read_text(encoding='utf-8'))
            book.update(status='selected', screening_date='2026-11-18',
                        discovered_by='foundational_reference',
                        selection_reason='Foundational definitions, post-processing, composition and Gaussian mechanism.')
            records[book['id']] = book
        selected = {k: v for k, v in records.items() if v.get('selected')}
        for key, value in selected.items():
            path = root / value['file']
            data = path.read_bytes()
            assert data.startswith(b'%PDF-'), path
            with fitz.open(path) as doc:
                pages = len(doc)
                assert pages > 0 and pages == value['pages'], path
                # Force every page object to load, not only the document header.
                for page in doc:
                    assert page.rect.width > 0 and page.rect.height > 0
            digest = hashlib.sha256(data).hexdigest()
            assert digest == value['sha256'], path
            text_path = root / 'text' / (path.stem + '.txt')
            assert text_path.exists() and text_path.stat().st_size > 100, text_path
            value.update(download_status='verified_pdf', pdf_verified='signature_all_page_objects_pages_sha256',
                         reading_level='abstract_screening_full_text_available')
            if key in READING[topic]:
                value.update(reading_level='abstract_and_selected_method_excerpts',
                             read_pdf_pages=READING[topic][key])
            value['model_reproduction'] = 'not_run'
        assert {p.name for p in root.glob('*.pdf')} == {v['file'] for v in selected.values()}, topic
        dump(root / 'papers-reviewed.json', records)
        dump(root / 'relevant-papers.json', selected)
        dump(root / 'citations/reading-log.json', {
            'date': '2026-11-18',
            'page_convention': 'PDF pages, starting at 1; selected excerpts, some partial.',
            'method_excerpt_pages': READING[topic],
            'other_selected_materials': 'Abstract screening; PDFs available; not represented as full-text method review.',
            'models_or_external_code_executed': False,
            'citation_traversal': 'Thematic and exact-ID retrieval; no complete forward/backward citation graph for this topic.',
        })
        count = len(selected)
        page_count = sum(v['pages'] for v in selected.values())
        totals[topic] = {'pdfs': count, 'pages': page_count, 'discovered_records': len(records)}
        lines = [f'# {title}：论文库与阅读索引', '', '[阅读中文综述](SUMMARY.md) · [全部研究总览](../RESEARCH_OVERVIEW.md)', '',
                 f'整理日期：2026-11-18。共 {count} 份有效 PDF，{page_count} 页；发现记录 {len(records)} 条。', '',
                 '## 研究范围与方法', '',
                 '采用 arXiv 主题检索与经典/直接相关工作的精确 ID 补查，选入与 Kinlin 项目接口、威胁模型和评估有关的材料。基础专著通过作者公开站点下载。', '',
                 '主题查询每组最多返回 45 条，按相关性排序；查询、返回总数和原始条目见 citations/search-results.json，所选 arXiv 元数据见 citations/selected-metadata.xml。Intent 主题沿用端云主题检索中的独立 intent_clarification 查询，已复制到本目录。', '',
                 '检索有关键词、排序和返回上限，不是全球穷尽检索。已选材料进行了人工相关性选择；未选条目的初始标记为粗筛，不能解释为每条均已独立精读或确定无关。评分表示本次阅读优先级，不是论文质量排名。', '',
                 '已验证 PDF 签名、全部页面对象、页数、文本抽取和 SHA-256。全文可用不等于逐页精读；方法选读页码记录在 citations/reading-log.json。未运行论文模型或下载的代码。', '',
                 'arXiv 年份按提交信息记录，正式发表信息以出版方为准；2026 年预印本不能自动视为同行评审结论。', '',
                 '## 全文清单', '',
                 '| # | 简称/ID | 论文标题与来源 | 本地全文 | 页数 | 阅读深度 |',
                 '|---|---|---|---|---:|---|']
        for i, (key, v) in enumerate(sorted(selected.items(), key=lambda item: item[1].get('published', item[0])), 1):
            depth = '摘要与方法选读' if key in READING[topic] else '摘要筛选；已下载全文'
            lines.append(f'| {i} | {v["short_name"]}<br>{v["id"]} | [{v["title"].replace("|", " / ")}]({v["url"]}) | [PDF]({v["file"]}) | {v["pages"]} | {depth} |')
        lines.extend(['', '## 文件说明', '',
                      '- SUMMARY.md：中文研究文章，区分论文结论、项目现状与设计建议。',
                      '- papers-reviewed.json：发现记录、选择状态、版本和摘要；未选不等于全文已审查。',
                      '- relevant-papers.json：本目录已选全文子集，含来源、页数、SHA-256 和阅读深度。',
                      '- citations/：原始检索和所选元数据、方法选读日志；没有宣称完成全量引用网络。',
                      '- text/：PDF 文本抽取；公式与版式以原 PDF 为准。',
                      '- ../planner/scripts/finalize_additional_topics.py：本地校验和索引生成脚本；不会覆盖综述。'])
        if topic == 'leading_model':
            lines.extend(['', '## 跨目录核心参考', '',
                          '- [SnD PDF](../differential_privacy/2310.09130_Split-and-Denoise.pdf)',
                          '- [DEL PDF](../differential_privacy/2602.11513_DP-Split-Stochastic-Quantization.pdf)',
                          '- [差分隐私综述](../differential_privacy/SUMMARY.md)', '',
                          '这两篇只在差分隐私目录保存，不计入本目录 19 份 PDF。'])
        (root / 'README.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    dump(BASE / 'planner/citations/additional-topics-validation.json', {'date': '2026-11-18', 'additional_topics': totals})
    print(json.dumps(totals, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
