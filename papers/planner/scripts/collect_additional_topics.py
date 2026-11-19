"""Collect reproducible public metadata for privacy and leading-model research."""
from pathlib import Path
import json,time,requests,xml.etree.ElementTree as ET,concurrent.futures as cf,re,hashlib,subprocess,sys
BASE=Path(__file__).resolve().parents[2]
NS={'a':'http://www.w3.org/2005/Atom'}
TOPICS={
'differential_privacy':{
 'activation_privacy':'(all:"differential privacy" OR all:"differentially private") AND (all:"split inference" OR all:"split learning" OR all:"activation" OR all:"prompt") AND (cat:cs.LG OR cat:cs.CR OR cat:cs.CL)',
 'private_llm_recent':'(ti:"differential privacy" OR ti:"differentially private") AND (all:"language model" OR all:"inference") AND submittedDate:[202501010000 TO 202611182359]',
 'accounting_foundations':'ti:"Deep Learning with Differential Privacy" OR ti:"Renyi Differential Privacy" OR ti:"Privacy of the Sampled Gaussian Mechanism" OR ti:"Subsampled Renyi Differential Privacy" OR ti:"Numerical Composition of Differential Privacy" OR ti:"Improving the Gaussian Mechanism" OR ti:"Privacy Odometers"',
},
'leading_model':{
 'split_llm':'(all:"split inference" OR ti:"split learning" OR ti:"Split-and-Denoise" OR ti:"SplitLLM" OR ti:"PrivateLoRA") AND (all:"language model" OR all:"transformer" OR all:"privacy")',
 'inversion':'ti:"Text Embeddings Reveal" OR ti:"Not All Embeddings" OR ti:"NoPeek" OR (ti:"split learning" AND (all:"inversion" OR all:"hijacking"))',
 'edge_cloud':'(ti:"edge-cloud" OR ti:"device-cloud" OR ti:"split inference") AND (all:"large language model" OR all:"LLM") AND submittedDate:[202501010000 TO 202611182359]',
 'intent_clarification':'ti:"IntentGPT" OR ti:"CLAMBER" OR ti:"Schema-Guided Dialogue" OR ti:"PICARD" OR ti:"RouteLLM" OR ti:"FrugalGPT" OR ti:"AskBench" OR (ti:"clarification" AND all:"language model")',
}}

def search(topic):
 root=BASE/topic;(root/'citations').mkdir(parents=True,exist_ok=True);(root/'text').mkdir(exist_ok=True)
 out={}
 for label,q in TOPICS[topic].items():
  for attempt in range(3):
   try:
    r=requests.get('https://export.arxiv.org/api/query',params={'search_query':q,'max_results':45,'sortBy':'relevance','sortOrder':'descending'},timeout=75);r.raise_for_status();f=ET.fromstring(r.content);break
   except Exception:
    if attempt==2:raise
    time.sleep(4)
  (root/'citations'/f'{label}.xml').write_text(r.text,encoding='utf-8')
  es=[]
  for e in f.findall('a:entry',NS):
   ident=e.findtext('a:id',namespaces=NS).rsplit('/',1)[-1]
   es.append(dict(id=ident,title=' '.join(e.findtext('a:title',namespaces=NS).split()),abstract=' '.join(e.findtext('a:summary',namespaces=NS).split()),published=e.findtext('a:published',namespaces=NS),updated=e.findtext('a:updated',namespaces=NS),authors=[a.findtext('a:name',namespaces=NS) for a in e.findall('a:author',NS)],url=f'https://arxiv.org/abs/{ident}',pdf=f'https://arxiv.org/pdf/{ident}'))
  out[label]={'query':q,'sort':'relevance','limit':45,'total':f.findtext('{http://a9.com/-/spec/opensearch/1.1/}totalResults'),'entries':es}
  print(topic,label,out[label]['total'],flush=True)
  for e in es:print(e['id'],e['title'],flush=True)
  (root/'citations/search-results.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');time.sleep(3)

def fetch(topic):
 root=BASE/topic;p=root/'papers-reviewed.json';records=json.loads(p.read_text(encoding='utf-8'))
 def one(v):
  if not v.get('selected'):return
  target=root/v['file']
  try:
   if target.exists():data=target.read_bytes()
   else:
    r=requests.get(v['pdf'],timeout=100);r.raise_for_status();data=r.content
   assert data.startswith(b'%PDF-')
   import fitz
   d=fitz.open(stream=data,filetype='pdf');assert len(d)>0
   target.write_bytes(data)
   subprocess.run(['pdftotext','-layout',str(target),str(root/'text'/(target.stem+'.txt'))],check=True,stderr=subprocess.DEVNULL)
   v.update(download_status='verified_pdf',pages=len(d),sha256=hashlib.sha256(data).hexdigest())
   return v['id'],len(d)
  except Exception as e:v.update(download_status='failed',error=str(e));return v['id'],str(e)
 with cf.ThreadPoolExecutor(4) as pool:
  for x in pool.map(one,[v for v in records.values() if v.get('selected')]):print(x,flush=True)
 p.write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
 print('complete',topic,flush=True)
if __name__=='__main__':{'search':search,'fetch':fetch}[sys.argv[1]](sys.argv[2])
