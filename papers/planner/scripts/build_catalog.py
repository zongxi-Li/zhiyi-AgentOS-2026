"""Create a traceable, manually scoped reading list from saved discovery records."""
from pathlib import Path
import json, re, requests, xml.etree.ElementTree as ET, hashlib
ROOT=Path(__file__).resolve().parents[1]
NS={'a':'http://www.w3.org/2005/Atom'}
search=json.loads((ROOT/'citations/search-results.json').read_text(encoding='utf-8'))
records={}
for label,batch in search.items():
    for e in batch['entries']:
        key=re.sub(r'v\d+$','',e['id'])
        if key not in records: records[key]={**e,'discovery_queries':[label]}
        elif label not in records[key]['discovery_queries']: records[key]['discovery_queries'].append(label)

selected={
'2210.02875':('Binder','program_execution'),
'2301.13808':('Dater','decomposition'),
'2310.00815':('ReAcTable','online_planning'),
'2401.04398':('Chain-of-Table','table_state'),
'2404.10150':('TabSQLify','decomposition'),
'2410.04739':('TableRAG','long_table_retrieval'),
'2508.18190':('ST-Raptor','hierarchical_tables'),
'2602.07034':('ST-Raptor-System','hierarchical_tables'),
'2506.13405':('RealHiTBench','benchmark'),
'2210.03629':('ReAct','online_planning'),
'2303.11366':('Reflexion','reflection_memory'),
'2308.10144':('ExpeL','experience_memory'),
'2402.02716':('LLM-Agent-Planning-Survey','planning_survey'),
'2502.12110':('A-MEM','experience_memory'),
'2611.22310':('EviDARL','multi_table_evidence'),
'2610.25131':('Data-Readme','table_relationships'),
'2610.04687':('GBDI-Imperfect-Tables','error_repair'),
'2610.03525':('ComInsight','evidence_reports'),
'2609.34157':('TableSeek','evidence_retrieval'),
'2607.22633':('SkillTGR','experience_memory'),
'2606.10316':('TabClaw','interactive_planning'),
'2603.07528':('TableMind-Plus-Plus','trained_agent'),
'2602.20017':('QUIETT','canonicalization'),
'2605.14465':('TABALIGN','cell_grounding'),
'2604.03393':('TABQAWORLD','multimodal_reasoning'),
'2603.09152':('DataFactory','multi_agent'),
'2609.03395':('TabScope','adaptive_scope'),
'2609.01216':('H2Table','hierarchical_tables'),
'2608.24082':('PARTAB','structured_evidence'),
'2607.17742':('Semantic-Answerability-Gap','evidence_retrieval'),
'2607.11207':('ProgramTab','program_execution'),
'2606.28916':('GRAB-Latent-Bridges','multi_table_graph'),
'2610.07749':('Cost-Effective-Numerical-QA','numerical_planning'),
'2602.14089':('TabTracer','search_planning'),
'2602.13059':('TraceBack','cell_attribution'),
'2602.09642':('MATA','multi_agent'),
'2601.02304':('Octopus','multi_table_discovery'),
}
seeds={
'2506.05813':('MAPLE.pdf','MAPLE','https://arxiv.org/abs/2506.05813v2'),
'2603.09151':('Deep-Tabular-Research_arXiv2026.pdf','DTR','https://arxiv.org/abs/2603.09151v2'),
'MACT':('MACT_Findings-NAACL2025.pdf','MACT','https://aclanthology.org/2025.findings-naacl.52/'),
'Table-Critic':('Table-Critic_ACL2025.pdf','Table-Critic',''),
'TALON':('TALON_EMNLP2025.pdf','TALON',''),
}
# Query original identifiers as well as foundational papers missing from broad top-N searches.
ids=list(dict.fromkeys([*selected,'2506.05813','2603.09151']))
r=requests.get('https://export.arxiv.org/api/query',params={'id_list':','.join(ids),'max_results':len(ids)},timeout=90)
r.raise_for_status(); (ROOT/'citations/selected-metadata.xml').write_text(r.text,encoding='utf-8')
for e in ET.fromstring(r.content).findall('a:entry',NS):
    ident=e.findtext('a:id',namespaces=NS).rsplit('/',1)[-1]; key=re.sub(r'v\d+$','',ident)
    item=dict(id=ident,title=' '.join(e.findtext('a:title',namespaces=NS).split()),
      abstract=' '.join(e.findtext('a:summary',namespaces=NS).split()),published=e.findtext('a:published',namespaces=NS),
      updated=e.findtext('a:updated',namespaces=NS),authors=[a.findtext('a:name',namespaces=NS) for a in e.findall('a:author',NS)],
      url=f'https://arxiv.org/abs/{ident}',pdf=f'https://arxiv.org/pdf/{ident}')
    records[key]={**records.get(key,{}),**item}

for key,p in records.items():
    p.update(screening_date='2026-11-18',download_selected=key in selected,reading_level='metadata_and_abstract_screening')
    if key in selected:
        name,category=selected[key]
        p.update(short_name=name,category=category,score=8,score_components={'topic':3,'method':3,'specificity':2},
            status='relevant',reason=f'Manually included: {category}; transferable to the five seed papers.',
            file=f'{key}_{name}.pdf',pdf_urls=[p['pdf']],source='arxiv_search_or_seed_reference')
    else:
        t=p['title'].lower()
        if any(z in t for z in ['reasoning','question answering','table retrieval','table-to','tabular','table parsing','table understanding']):
            p.update(score=6,status='possible_extension',reason='Adjacent direction; outside the selected implementation-focused core or overlapping coverage.')
        else:p.update(score=2,status='excluded',reason='Keyword collision or insufficient direct connection to table-agent planning.')

for key,(filename,name,url) in seeds.items():
    p=records.get(key,{'id':key,'title':name,'url':url})
    import fitz
    pdf=ROOT/filename; d=fitz.open(pdf)
    p.update(short_name=name,file=filename,source='user_provided',score=10,status='seed',
        reading_level='full_text_methods_results_appendix',download_selected=False,download_status='user_provided_verified_pdf',
        sha256=hashlib.sha256(pdf.read_bytes()).hexdigest(),pages=len(d),screening_date='2026-11-18')
    records[key]=p

for key,title,name,urls,url in [
('10.18653/v1/2024.acl-long.692','TaPERA: Enhancing Faithfulness and Interpretability in Long-Form Table QA by Content Planning and Execution-based Reasoning','TaPERA',['https://aclanthology.org/2024.acl-long.692.pdf'],'https://aclanthology.org/2024.acl-long.692/'),
('10.14778/3685800.3685816','AutoTQA: Towards Autonomous Tabular Question Answering through Multi-Agent Large Language Models','AutoTQA',['https://www.vldb.org/pvldb/vol17/p3920-zhu.pdf'],'https://doi.org/10.14778/3685800.3685816')]:
    records[key]=dict(id=key,title=title,short_name=name,url=url,pdf_urls=urls,file=f'2024_{name}.pdf',
        score=9,status='relevant',category='planning_execution',download_selected=True,source='seed_reference_crossref_verified',
        screening_date='2026-11-18',reading_level='metadata_screening_pending_pdf')
(ROOT/'papers-reviewed.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
print('Screened records:',len(records),'new PDFs selected:',sum(p['download_selected'] for p in records.values()))
for key in selected:
    print(key,records[key]['title'])
