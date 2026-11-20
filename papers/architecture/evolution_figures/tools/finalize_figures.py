"""Validate native/derived figures, merge vector PDFs, and package deliverables."""
from pathlib import Path
from xml.etree import ElementTree as ET
from hashlib import sha256
from zipfile import ZipFile, ZIP_DEFLATED
import json
import re
import fitz
from PIL import Image, ImageOps, ImageDraw

BASE = Path(__file__).resolve().parents[1]


def overlap(a, b, tolerance=1):
    return (min(a['x']+a['w'], b['x']+b['w']) > max(a['x'], b['x'])+tolerance
            and min(a['y']+a['h'], b['y']+b['h']) > max(a['y'], b['y'])+tolerance)


def segment_hits_box(a, b, n):
    # Exact clipping against an inset rectangle, excluding border-only contact.
    xmin, xmax = n['x']+1, n['x']+n['w']-1
    ymin, ymax = n['y']+1, n['y']+n['h']-1
    lo, hi = 0., 1.
    for value, delta, lower, upper in [(a['x'],b['x']-a['x'],xmin,xmax),
                                        (a['y'],b['y']-a['y'],ymin,ymax)]:
        if abs(delta)<1e-9:
            if value<lower or value>upper:return False
        else:
            t1,t2=sorted(((lower-value)/delta,(upper-value)/delta))
            lo,hi=max(lo,t1),min(hi,t2)
            if lo>hi:return False
    return True


def main():
    specs=json.loads((BASE/'.build/figures.json').read_text(encoding='utf-8'))
    renders={r['figure']:r for r in json.loads((BASE/'.build/render-validation.json').read_text(encoding='utf-8'))}
    xml_checks=json.loads((BASE/'.build/xml-validation.json').read_text(encoding='utf-8'))
    rows=[]
    for f in specs:
        stem=f['key']+'_'+f['lang']; r=renders[stem]
        nodes=[n for n in f['spec'] if n['role']=='node']
        label_pairs=[]; outside=[]; overflow=[]; crossings=[]
        for i,l in enumerate(r['labels']):
            b=l['box']; c=l['cell']
            if b['x']<-1 or b['y']<-1 or b['x']+b['w']>f['width']+1 or b['y']+b['h']>f['height']+1:outside.append(l['id'])
            if not l['edge'] and (b['x']<c['x']-2 or b['y']<c['y']-2 or b['x']+b['w']>c['x']+c['w']+2 or b['y']+b['h']>c['y']+c['h']+2):overflow.append(l['id'])
            for other in r['labels'][i+1:]:
                if overlap(b,other['box']):label_pairs.append([l['id'],other['id']])
        for e in r['edges']:
            if '_line_life' in e['id']:continue # Sequence activation blocks intentionally cover lifelines.
            for n in nodes:
                if n['id'] in [e.get('source'),e.get('target')]:continue
                if any(segment_hits_box(a,b,n) for a,b in zip(e['points'],e['points'][1:])):crossings.append([e['id'],n['id']])
        assert not (label_pairs or outside or overflow or crossings),(stem,label_pairs,outside,overflow,crossings)
        svg_text=(BASE/'svg'/f'{stem}.svg').read_text(encoding='utf-8')
        svg=ET.fromstring(svg_text)
        assert svg.get('viewBox')==f"0 0 {f['width']} {f['height']}"
        assert not any(n.tag.rsplit('}',1)[-1] in ['foreignObject','image','script'] for n in svg.iter())
        assert not any('<br' in (n.text or '') for n in svg.iter())
        assert 'light-dark(' not in svg_text
        assert not re.search(r'(?:href|src)="https?://',svg_text)
        texts=[n for n in svg.iter() if n.tag.rsplit('}',1)[-1]=='text']
        assert len(texts)>=len([n for n in f['spec'] if n.get('text') and n['role']!='edge'])
        with fitz.open(BASE/'pdf'/f'{stem}.pdf') as doc:
            assert len(doc)==1
            page=doc[0]; mmw=page.rect.width/72*25.4
            assert abs(mmw-180)<.2
            assert abs(page.rect.height/page.rect.width-f['height']/f['width'])<.002
            assert not page.get_images(full=True)
            expected_text_chars=sum(len(''.join(n.get('text','').split())) for n in f['spec'])
            assert len(''.join(page.get_text().split())) >= expected_text_chars * .95
            fonts=page.get_fonts(full=True)
            assert fonts and all(doc.extract_font(font[0])[3] for font in fonts)
            spans=[s for block in page.get_text('dict')['blocks'] if 'lines' in block for line in block['lines'] for s in line['spans'] if s['text'].strip()]
            min_font=min(s['size'] for s in spans)
            assert min_font>=8.0,(stem,min_font)
            pdf_text=page.get_text()
            assert '\ufffd' not in pdf_text
        with Image.open(BASE/'png'/f'{stem}.png') as im:
            assert im.size==(f['width']*2,f['height']*2)
            png_size=list(im.size)
        rows.append(dict(figure=stem,viewBox=svg.get('viewBox'),svg_text_elements=len(texts),
                         foreign_objects=0,raster_images=0,external_resources=0,
                         pdf_pages=1,pdf_width_mm=round(mmw,3),minimum_pdf_font_pt=round(min_font,3),
                         embedded_fonts=len(fonts),selectable_pdf_text=True,png_pixels=png_size,
                         labels_outside_canvas=outside,vertex_label_overflow=overflow,
                         label_overlap_pairs=label_pairs,edges_through_unrelated_nodes=crossings))
    groups=json.loads((BASE/'.build/groups.json').read_text(encoding='utf-8'))
    groups['Evolution_All_Figures']=[f['key'] for f in specs if f['lang']=='en']
    for lang in ['en','zh']:
        for group, keys in groups.items():
            root=ET.parse(BASE/'drawio'/f'{group}_{lang}.drawio').getroot()
            assert len(root.findall('diagram'))==len(keys)
            merged=fitz.open()
            for key in keys:
                with fitz.open(BASE/'pdf'/f'{key}_{lang}.pdf') as source:merged.insert_pdf(source)
            merged.set_metadata({'title':f'Kinlin {group} ({lang})','author':'Kinlin architecture research','subject':'Proposed architecture; see CAPTIONS.md and LOGIC_REVIEW.md'})
            merged.save(BASE/'pdf'/f'{group}_{lang}.pdf',garbage=4,deflate=True)
            merged.close()
        keys=groups['Evolution_All_Figures']
        sheet=Image.new('RGB',(2100,1740),'#e6e9ec'); draw=ImageDraw.Draw(sheet)
        for idx,key in enumerate(keys):
            with Image.open(BASE/'png'/f'{key}_{lang}.png') as source:
                thumb=ImageOps.contain(source.convert('RGB'),(680,530),Image.Resampling.LANCZOS)
                x=10+(idx%3)*700; y=35+(idx//3)*580
                sheet.paste(thumb,(x+(680-thumb.width)//2,y+(530-thumb.height)//2))
                draw.text((x+10,y-22),f'{key.upper()} / {lang}',fill='#243746')
        sheet.save(BASE/'png'/f'Evolution_Overview_{lang}.png',dpi=(200,200))
    report={
        'date':'2026-11-19','scope':'Nine proposed graph and skill evolution figures, English and Chinese',
        'native_drawio_pages_per_language':9,'xml_checks':xml_checks,'export_checks':rows,
        'renderer':{'source':'https://www.draw.io/js/viewer.min.js',
                    'sha256':sha256((BASE/'.build/viewer.min.js').read_bytes()).hexdigest(),
                    'engine':'Official draw.io Graph / mxCodec / getSvg; SVG text conversion enabled',
                    'network':'Loopback-only rendering; external browser requests blocked'},
        'visual_review':{'method':'Per-figure inspection of English and Chinese PNG exports; not inferred from XML validation',
                         'figures':list(renders),'status':'completed'},
        'logic_review':'Design consistency only; see LOGIC_REVIEW.md',
        'not_validated':['Production graph or skill evolution implementation', 'Generalization or monotonic quality gains', 'Crash/concurrency correctness of a running publisher', 'Formal privacy guarantees', 'Compliance with a specific conference template'],
    }
    delivered=[]
    for folder in ['drawio','svg','pdf','png','tools']:
        delivered.extend(sorted(p for p in (BASE/folder).iterdir() if p.is_file() and p.suffix in ['.drawio','.svg','.pdf','.png','.py','.cjs','.html']))
    delivered.extend(BASE/name for name in ['README.md','CAPTIONS.md','LOGIC_REVIEW.md','FIGURE_PLAN.md'])
    report['files']=[{'path':p.relative_to(BASE).as_posix(),'bytes':p.stat().st_size,'sha256':sha256(p.read_bytes()).hexdigest()} for p in delivered]
    (BASE/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    with ZipFile(BASE/'Evolution_Figures_Package.zip','w',ZIP_DEFLATED) as archive:
        for p in delivered+[BASE/'validation.json']:archive.write(p,p.relative_to(BASE).as_posix())
    print(json.dumps({'figures':len(rows),'drawio_files':len(list((BASE/'drawio').glob('*.drawio'))),
                      'minimum_pdf_font_pt':min(r['minimum_pdf_font_pt'] for r in rows),
                      'zip_bytes':(BASE/'Evolution_Figures_Package.zip').stat().st_size,
                      'status':'passed'},indent=2))


if __name__=='__main__':main()
