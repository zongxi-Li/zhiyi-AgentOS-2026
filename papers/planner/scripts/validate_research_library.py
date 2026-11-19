"""Check the six research collections and their Markdown entry points."""
from pathlib import Path
import hashlib
import json
import re

import fitz

BASE = Path(__file__).resolve().parents[2]
TOPICS = ['planner', 'differential_privacy', 'leading_model', 'intent_model',
          'graph_evolution', 'skills_evolution']


def main():
    totals, hashes, broken = {}, {}, []
    for topic in TOPICS:
        root = BASE / topic
        records = json.loads((root / 'relevant-papers.json').read_text(encoding='utf-8'))
        pages = 0
        for value in records.values():
            path = root / value['file']
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            assert data.startswith(b'%PDF-') and digest == value['sha256'], path
            with fitz.open(path) as doc:
                assert len(doc) == value['pages'], path
                pages += len(doc)
                for page in doc:
                    assert page.rect.width > 0 and page.rect.height > 0, path
            text_path = root / 'text' / (path.stem + '.txt')
            assert text_path.exists() and text_path.stat().st_size > 100, text_path
            hashes.setdefault(digest, []).append(str(path.relative_to(BASE)))
        assert {p.name for p in root.glob('*.pdf')} == {v['file'] for v in records.values()}, root
        totals[topic] = {'pdfs': len(records), 'pages': pages,
                         'all_page_objects_loaded': True, 'sha256_matches_manifest': True,
                         'extracted_text_present': True}
    markdown = [BASE / 'RESEARCH_OVERVIEW.md', BASE / 'EVOLUTION_IMPLEMENTATION_PLAN.md'] + [
        BASE / t / f for t in TOPICS for f in ['README.md', 'SUMMARY.md']]
    for path in markdown:
        source = path.read_text(encoding='utf-8')
        for label, target in re.findall(r'\[([^\]]*)\]\(([^)]+)\)', source):
            if re.match(r'^(https?://|#|mailto:)', target):
                continue
            local = target.split('#')[0]
            if not (path.parent / local).exists():
                broken.append({'source': str(path.relative_to(BASE)), 'label': label, 'target': target})
    duplicates = [v for v in hashes.values() if len(v) > 1]
    assert not broken, broken
    assert not duplicates, duplicates
    pdfs = sum(v['pdfs'] for v in totals.values())
    report = {'date': '2026-11-18', 'topics': totals, 'total_pdfs': pdfs,
              'total_pages': sum(v['pages'] for v in totals.values()), 'seed_pdfs': 5,
              'new_downloads': pdfs - 5, 'markdown_files_checked': len(markdown),
              'broken_local_links': broken, 'duplicate_pdf_hashes': duplicates,
              'model_reproduction': 'not_run', 'business_code_changed': False}
    (BASE / 'research-validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
