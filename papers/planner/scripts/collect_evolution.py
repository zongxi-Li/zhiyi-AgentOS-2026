"""Public metadata discovery for graph/workflow and reusable skill evolution."""
from pathlib import Path
import json
import re
import sys
import time
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup

BASE = Path(__file__).resolve().parents[2]
NS = {'a': 'http://www.w3.org/2005/Atom'}
QUERIES = {
    'graph_evolution': {
        'workflow_foundations': 'ti:"AFlow" OR ti:"Automated Design of Agentic Systems" OR ti:"GPTSwarm" OR ti:"AgentPrune" OR ti:"DyLAN" OR ti:"Multi-agent Architecture Search"',
        'workflow_evolution': '(all:"workflow optimization" OR all:"workflow evolution" OR all:"graph evolution" OR all:"self-evolving") AND (ti:agent OR ti:agentic OR ti:workflow) AND (cat:cs.AI OR cat:cs.CL OR cat:cs.LG)',
        'dynamic_graph': '(ti:"agent" OR ti:"multi-agent") AND (ti:"topology" OR ti:"graph" OR ti:"evolution") AND submittedDate:[202501010000 TO 202611182359]',
        'optimization_tools': 'ti:"TextGrad" OR ti:"GEPA" OR ti:"DSPy" OR ti:"Agentic Context Engineering"',
    },
    'skills_evolution': {
        'skills_foundations': 'ti:"Voyager" OR ti:"DreamCoder" OR ti:"LILO" OR ti:"SkillFlow" OR ti:"ToolMaker" OR ti:"CREATOR" OR ti:"LATM"',
        'skills_self_evolution': '(ti:skill OR ti:skills OR ti:tool OR ti:tools) AND (all:"self-evolving" OR all:"self-improving" OR all:"skill library" OR all:"skill evolution") AND (all:"language model" OR all:"agent")',
        'agent_self_improvement': 'ti:"Darwin Godel Machine" OR ti:"Darwin Gödel Machine" OR ti:"Self-Improving Coding Agent" OR ti:"AgentEvolver" OR ti:"SkillRL" OR ti:"SkillBank" OR ti:"SICA"',
        'experience_learning': 'ti:"Learning on the Job" OR ti:"Agent Workflow Memory" OR ti:"LearnAct" OR ti:"Self-Evolving Agents" OR ti:"Procedural Memory"',
    },
}
HTML_QUERIES = {
    'graph_evolution': {
        'workflow_optimization_html': 'agent workflow evolution optimization',
        'topology_html': 'multi-agent topology optimization',
        'named_methods_html': 'GPTSwarm OR AgentPrune OR DyLAN OR AFlow OR GEPA',
        'memory_graph_html': '"G-Memory" OR "Zep" OR "Graphiti"',
    },
    'skills_evolution': {
        'skill_evolution_html': 'agent skill evolution',
        'named_skills_html': 'SkillRL OR SkillBank OR AgentEvolver OR ToolMaker',
        'self_modification_html': 'Darwin Godel OR self-improving agent',
        'workflow_memory_html': 'Agent Workflow Memory OR Learning on the Job',
        'skill_graph_html': '"SkillNet" OR "AgentSkillOS" OR "Memento-Skills" OR "SkillWeaver"',
    },
}


def html_search(topic):
    root = BASE / topic
    out = json.loads((root / 'citations/search-results.json').read_text(encoding='utf-8'))
    records = json.loads((root / 'papers-reviewed.json').read_text(encoding='utf-8'))
    for label, q in HTML_QUERIES[topic].items():
        if label in out:
            continue
        response = requests.get('https://arxiv.org/search/', params={
            'query': q, 'searchtype': 'all', 'abstracts': 'show', 'order': '-announced_date_first', 'size': 50}, timeout=60)
        response.raise_for_status()
        (root / 'citations' / f'{label}.html').write_text(response.text, encoding='utf-8')
        soup = BeautifulSoup(response.text, 'html.parser')
        entries = []
        for item in soup.select('li.arxiv-result'):
            url = item.select_one('.list-title a')['href']
            ident = url.rsplit('/', 1)[-1]
            abstract = item.select_one('.abstract-full')
            v = dict(id=ident, title=item.select_one('p.title').get_text(' ', strip=True),
                abstract=abstract.get_text(' ', strip=True).removesuffix('△ Less').strip() if abstract else '',
                authors=[a.get_text(' ', strip=True) for a in item.select('p.authors a')],
                url=url, pdf=f'https://arxiv.org/pdf/{ident}')
            entries.append(v)
            key = re.sub(r'v\d+$', '', ident)
            if key not in records:
                records[key] = {**v, 'discovered_by': [], 'selected': False, 'screening_status': 'unreviewed_discovery'}
            records[key]['discovered_by'].append(label)
        out[label] = {'query': q, 'endpoint': response.url, 'date': '2026-11-18',
                      'sort': '-announced_date_first', 'limit': 50, 'entries': entries}
        (root / 'citations/search-results.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
        (root / 'papers-reviewed.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
        print(topic, label, len(entries), flush=True)
        for e in entries:
            print(e['id'], e['title'], flush=True)
        time.sleep(3)


def query(q, *, limit=40, ids=False):
    params = {'id_list': q, 'max_results': limit} if ids else {
        'search_query': q, 'max_results': limit, 'sortBy': 'relevance', 'sortOrder': 'descending'}
    for attempt in range(3):
        try:
            response = requests.get('https://export.arxiv.org/api/query', params=params, timeout=60)
            response.raise_for_status()
            feed = ET.fromstring(response.content)
            entries = []
            for e in feed.findall('a:entry', NS):
                ident = e.findtext('a:id', namespaces=NS).rsplit('/', 1)[-1]
                entries.append(dict(id=ident, title=' '.join(e.findtext('a:title', namespaces=NS).split()),
                    abstract=' '.join(e.findtext('a:summary', namespaces=NS).split()),
                    published=e.findtext('a:published', namespaces=NS), updated=e.findtext('a:updated', namespaces=NS),
                    authors=[a.findtext('a:name', namespaces=NS) for a in e.findall('a:author', NS)],
                    url=f'https://arxiv.org/abs/{ident}', pdf=f'https://arxiv.org/pdf/{ident}'))
            return response.text, entries, feed.findtext('{http://a9.com/-/spec/opensearch/1.1/}totalResults')
        except Exception:
            if attempt == 2:
                raise
            time.sleep(3)


def search(topic):
    root = BASE / topic
    (root / 'citations').mkdir(parents=True, exist_ok=True)
    (root / 'text').mkdir(exist_ok=True)
    out, records = {}, {}
    for label, q in QUERIES[topic].items():
        raw, entries, total = query(q)
        (root / 'citations' / f'{label}.xml').write_text(raw, encoding='utf-8')
        out[label] = {'query': q, 'date': '2026-11-18', 'sort': 'relevance', 'limit': 40, 'total': total, 'entries': entries}
        for v in entries:
            key = re.sub(r'v\d+$', '', v['id'])
            if key not in records:
                records[key] = {**v, 'discovered_by': [], 'selected': False, 'screening_status': 'unreviewed_discovery'}
            records[key]['discovered_by'].append(label)
        (root / 'citations/search-results.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
        (root / 'papers-reviewed.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
        print(topic, label, 'total', total, flush=True)
        for e in entries:
            print(e['id'], e['title'], flush=True)
        time.sleep(3)


if __name__ == '__main__':
    (html_search if len(sys.argv) > 2 and sys.argv[2] == 'html' else search)(sys.argv[1])
