"""Reproduce public arXiv discovery/downloads; never executes retrieved content."""
from pathlib import Path
import concurrent.futures as cf
import hashlib
import json
import re
import subprocess
import time
import xml.etree.ElementTree as ET
import requests

ROOT = Path(__file__).resolve().parents[1]
NS = {'a': 'http://www.w3.org/2005/Atom', 'ar': 'http://arxiv.org/schemas/atom'}
QUERIES = {
    'recent_table_agents': 'ti:table AND (all:agent OR all:planning) AND submittedDate:[202601010000 TO 202611182359]',
    'table_reasoning': 'ti:table AND (all:reasoning OR all:retrieval) AND submittedDate:[202601010000 TO 202611182359]',
    'foundational': 'ti:"Chain-of-Table" OR ti:ReAcTable OR ti:TableRAG OR ti:TabSQLify OR ti:TaPERA OR ti:AutoTQA OR ti:"ST-Raptor" OR ti:RealHiTBench OR ti:"Binding Language Models" OR ti:"Large Language Models are Versatile"',
    'experience_planning': 'ti:Reflexion OR ti:"ExpeL" OR ti:"ReAct" OR ti:"Understanding the planning of LLM agents"',
}

def search():
    out = {}
    for label, query in QUERIES.items():
        response = requests.get('https://export.arxiv.org/api/query', params={
            'search_query': query, 'max_results': 60,
            'sortBy': 'submittedDate', 'sortOrder': 'descending'}, timeout=60)
        response.raise_for_status()
        (ROOT/'citations'/f'{label}.xml').write_text(response.text, encoding='utf-8')
        feed = ET.fromstring(response.content)
        entries = []
        for e in feed.findall('a:entry', NS):
            ident = e.findtext('a:id', namespaces=NS).rsplit('/', 1)[-1]
            entries.append(dict(id=ident, title=' '.join(e.findtext('a:title', namespaces=NS).split()),
                abstract=' '.join(e.findtext('a:summary', namespaces=NS).split()),
                published=e.findtext('a:published', namespaces=NS),
                updated=e.findtext('a:updated', namespaces=NS),
                authors=[a.findtext('a:name', namespaces=NS) for a in e.findall('a:author', NS)],
                url=f'https://arxiv.org/abs/{ident}', pdf=f'https://arxiv.org/pdf/{ident}'))
        out[label] = dict(query=query, total=feed.findtext('{http://a9.com/-/spec/opensearch/1.1/}totalResults'), entries=entries)
        print(label, out[label]['total'], flush=True)
        for e in entries:
            print(e['id'], e['title'], flush=True)
        time.sleep(3)
    (ROOT/'citations'/'search-results.json').write_text(json.dumps(out, ensure_ascii=False, indent=2),encoding='utf-8')

def download_one(paper):
    target=ROOT/paper['file']
    if target.exists():
        return paper['id'], 'exists'
    errors=[]
    for url in paper['pdf_urls']:
        try:
            r=requests.get(url, timeout=90)
            r.raise_for_status()
            if not r.content.startswith(b'%PDF-'):
                raise ValueError('Response is not a PDF')
            import fitz
            doc=fitz.open(stream=r.content, filetype='pdf')
            if not len(doc): raise ValueError('Empty PDF')
            target.write_bytes(r.content)
            paper.update(download_url=url, pages=len(doc),sha256=hashlib.sha256(r.content).hexdigest(),download_status='verified_pdf')
            subprocess.run(['pdftotext','-layout',str(target),str(ROOT/'text'/(target.stem+'.txt'))],check=True)
            return paper['id'], f'OK {len(doc)} pages'
        except Exception as exc: errors.append(f'{url}: {exc}')
    paper.update(download_status='failed',errors=errors)
    return paper['id'],errors

def download():
    path=ROOT/'papers-reviewed.json'
    papers=json.loads(path.read_text(encoding='utf-8'))
    selected=[p for p in papers.values() if p.get('download_selected')]
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(download_one,selected): print(result,flush=True)
    path.write_text(json.dumps(papers,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':
    import sys
    {'search':search,'download':download}[sys.argv[1]]()
