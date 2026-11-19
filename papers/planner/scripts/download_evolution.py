"""Resolve selected arXiv detail pages, then download and validate public PDFs.

Run metadata first so titles, dates and versions can be reviewed before fetch.
"""
from pathlib import Path
import concurrent.futures as cf
import hashlib
import json
import re
import subprocess
import sys
import time

import fitz
import requests
from bs4 import BeautifulSoup

BASE = Path(__file__).resolve().parents[2]
SELECTIONS = {
    'graph_evolution': {
        '2402.16823': 'GPTSwarm', '2408.08435': 'ADAS', '2410.10762': 'AFlow',
        '2502.04180': 'MaAS', '2510.02669': 'AutoMaAS',
        '2406.07496': 'TextGrad', '2310.03714': 'DSPy', '2507.19457': 'GEPA',
        '2611.16378': 'Evidence-Governed-Adoption', '2610.29005': 'VeriEvolve',
        '2610.15150': 'Harmony-Harness', '2609.37953': 'Topological-Coherence',
        '2608.10504': 'MEGA-Wisdom-Graph', '2608.09096': 'Evo-Bench',
        '2606.28374': 'Held-Out-Selection', '2606.27492': 'QueenBee',
        '2605.09315': 'Lifelong-Degradation',
        '2609.37151': 'FlowMAS', '2609.05774': 'Inference-Time-Graph-Engineering',
        '2609.04217': 'Equal-Cost-Structure', '2610.09239': 'Winners-Curse',
        '2610.05284': 'Workflow-Graph-Fusion',
        '2506.07398': 'G-Memory', '2501.13956': 'Zep-Temporal-Graph',
    },
    'skills_evolution': {
        '2305.16291': 'Voyager', '2006.08381': 'DreamCoder', '2310.19791': 'LILO',
        '2504.06188': 'SkillFlow-Retrieval', '2605.14089': 'SkillFlow-Evolution',
        '2505.22954': 'Darwin-Godel-Machine', '2409.07429': 'Agent-Workflow-Memory',
        '2504.15228': 'SICA',
        '2611.22610': 'EvoSkill-S1', '2611.14019': 'Patchable-Skill-Evolution',
        '2611.06444': 'EvoGuard', '2611.04456': 'Skills-GitHub-Empirical',
        '2610.36188': 'Skill-Dreaming', '2610.34260': 'MultiEvoSkill',
        '2610.25126': 'Skill-Library-Lifecycle', '2610.24630': 'Selm',
        '2611.10542': 'Experience-Backdoor',
        '2602.08234': 'SkillRL', '2511.10395': 'AgentEvolver',
        '2305.17126': 'LLMs-as-Tool-Makers', '2606.09316': 'Anything2Skill',
        '2608.22793': 'TRACE-Skill-Bank', '2610.14515': 'SEPM-Task-Graphs',
        '2603.18743': 'Memento-Skills', '2603.04448': 'SkillNet',
        '2603.02176': 'AgentSkillOS', '2504.07079': 'SkillWeaver',
    },
}


def read_records(topic):
    root = BASE / topic
    return root, json.loads((root / 'papers-reviewed.json').read_text(encoding='utf-8'))


def save(root, records):
    (root / 'papers-reviewed.json').write_text(json.dumps(records, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def metadata(topic):
    root, records = read_records(topic)
    def one(pair):
        key, short = pair
        path = root / 'citations' / f'{key}-abstract.html'
        if path.exists():
            raw = path.read_text(encoding='utf-8')
        else:
            response = requests.get(f'https://arxiv.org/abs/{key}', timeout=45)
            response.raise_for_status()
            raw = response.text
            path.write_text(raw, encoding='utf-8')
        soup = BeautifulSoup(raw, 'html.parser')
        def meta(name):
            tag = soup.select_one(f'meta[name="{name}"]')
            return tag.get('content') if tag else None
        title = meta('citation_title')
        assert title, key
        history = soup.select_one('.submission-history').get_text(' ', strip=True)
        versions = re.findall(r'\[v(\d+)\]', history)
        ident = key + 'v' + max(versions, key=int)
        published = meta('citation_date')
        assert published and published.replace('/', '-') <= '2026-11-18', (key, published)
        return key, dict(id=ident, title=title, abstract=meta('citation_abstract') or '',
            authors=[m['content'] for m in soup.select('meta[name="citation_author"]')],
            published=published.replace('/', '-'), updated=(meta('citation_online_date') or '').replace('/', '-'),
            url=f'https://arxiv.org/abs/{ident}', pdf=f'https://arxiv.org/pdf/{ident}',
            short_name=short, file=f'{key}_{short}.pdf', selected=True,
            screening_status='selected_after_title_abstract_review', score=8,
            selection_reason='Agent workflow or skill evolution mechanism, evaluation, or lifecycle relevance.',
            reading_level='abstract_screening_full_text_available', submission_history=history,
            metadata_source=f'https://arxiv.org/abs/{key}', metadata_snapshot=str(path.relative_to(root)))
    with cf.ThreadPoolExecutor(max_workers=3) as pool:
        for key, value in pool.map(one, SELECTIONS[topic].items()):
            records[key] = {**records.get(key, {}), **value}
            print(key, value['title'], value['published'], flush=True)
            save(root, records)


def fetch(topic):
    root, records = read_records(topic)
    def one(value):
        target = root / value['file']
        try:
            for attempt in range(3):
                try:
                    if target.exists():
                        data = target.read_bytes()
                    else:
                        response = requests.get(value['pdf'], timeout=70)
                        response.raise_for_status()
                        data = response.content
                    assert data.startswith(b'%PDF-')
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    time.sleep(4)
            with fitz.open(stream=data, filetype='pdf') as doc:
                assert len(doc) > 0
                pages = len(doc)
                for page in doc:
                    assert page.rect.width > 0
            target.write_bytes(data)
            subprocess.run(['pdftotext', '-layout', str(target), str(root / 'text' / (target.stem + '.txt'))], check=True, stderr=subprocess.DEVNULL)
            value.update(download_status='verified_pdf', pages=pages, sha256=hashlib.sha256(data).hexdigest())
            return value['id'], pages
        except Exception as exc:
            value.update(download_status='failed', download_error=str(exc))
            return value['id'], str(exc)
    with cf.ThreadPoolExecutor(max_workers=3) as pool:
        for result in pool.map(one, [v for v in records.values() if v.get('selected')]):
            print(result, flush=True)
    save(root, records)


if __name__ == '__main__':
    {'metadata': metadata, 'fetch': fetch}[sys.argv[1]](sys.argv[2])
