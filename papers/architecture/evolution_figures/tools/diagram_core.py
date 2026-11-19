"""Author bilingual, editable evolution schematics as uncompressed draw.io XML."""
from pathlib import Path
from xml.etree import ElementTree as ET
import json

BASE = Path(__file__).resolve().parents[1]
P = {
    'ink': '#243746', 'line': '#617482', 'blue': '#3D6F9C', 'blue_fill': '#ECF2F8',
    'teal': '#267C78', 'teal_fill': '#EAF4F1', 'purple': '#74658C', 'purple_fill': '#F1EEF6',
    'gray': '#78838D', 'gray_fill': '#F4F5F6', 'orange': '#A85A32', 'orange_fill': '#FFF1E8',
}


class Figure:
    def __init__(self, key, title, zh_title, width, height, lang):
        self.key, self.lang, self.w, self.h = key, lang, width, height
        self.font = 'Arial' if lang == 'en' else 'Microsoft YaHei'
        self.name = title if lang == 'en' else zh_title
        self.diagram = ET.Element('diagram', id=f'{key}-{lang}', name=self.name)
        self.model = ET.SubElement(self.diagram, 'mxGraphModel', dx=str(width), dy=str(height),
            grid='1', gridSize='10', guides='1', tooltips='1', connect='1', arrows='1', fold='1',
            page='1', pageScale='1', pageWidth=str(width), pageHeight=str(height), math='0', shadow='0')
        self.root = ET.SubElement(self.model, 'root')
        ET.SubElement(self.root, 'mxCell', id='0')
        ET.SubElement(self.root, 'mxCell', id='1', parent='0')
        self.cells, self.spec = {}, []
        self.box('canvas', '', '', 0, 0, width, height, 'gray', fill='#FFFFFF', stroke='none', role='background')
        self.text('title', title, zh_title, 40, 24, width-80, 44, 32, True)

    def tr(self, en, zh):
        return en if self.lang == 'en' else zh

    def box(self, ident, en, zh, x, y, w, h, color='blue', *, fill=None, stroke=None,
            role='node', shape='rect', size=26, bold=False, dashed=False, align='center'):
        ident = f'{self.key}_{ident}'
        assert ident not in self.cells
        style = (f'shape={shape};rounded=1;arcSize=8;whiteSpace=wrap;html=0;convertToSvg=1;svgWhiteSpace=wrap;'
                 f'fillColor={fill or P[color+"_fill"]};strokeColor={stroke or P[color]};'
                 f'strokeWidth=1.5;fontColor={P["ink"]};fontSize={size};fontFamily={self.font};'
                 f'fontStyle={1 if bold else 0};align={align};verticalAlign=middle;spacing=12;'
                 f'shadow=0;glass=0;dashed={1 if dashed else 0};')
        cell = ET.SubElement(self.root, 'mxCell', id=ident, value=self.tr(en, zh), style=style, vertex='1', parent='1')
        ET.SubElement(cell, 'mxGeometry', x=str(x), y=str(y), width=str(w), height=str(h), attrib={'as':'geometry'})
        self.cells[ident] = (x, y, w, h)
        self.spec.append(dict(id=ident, role=role, text=self.tr(en,zh), x=x,y=y,w=w,h=h,size=size))
        return ident

    def text(self, ident, en, zh, x,y,w,h,size=24,bold=False,color='ink',align='left'):
        ident=self.box(ident,en,zh,x,y,w,h,'gray',fill='none',stroke='none',role='text',size=size,bold=bold,align=align)
        cell=self.root.find(f"mxCell[@id='{ident}']")
        cell.set('style',cell.get('style').replace(f'fontColor={P["ink"]}',f'fontColor={P.get(color,color)}').replace('spacing=12','spacing=0'))
        return ident

    def frame(self, ident,en,zh,x,y,w,h,color='gray',dashed=False):
        ident=self.box(ident,'','',x,y,w,h,color,fill='none',role='frame',dashed=dashed)
        self.text(ident.split('_')[-1]+'-heading',en,zh,x+18,y+12,w-36,40,26,True,color)
        return ident

    def edge(self, ident, source, target, en='',zh='', *, color='line', dashed=False,
             exit=(1,.5),entry=(0,.5),points=None,label_dy=0,label_dx=0,arrow=True):
        ident=f'{self.key}_e_{ident}'
        style=(f'edgeStyle=none;rounded=0;html=0;convertToSvg=1;endArrow={"block" if arrow else "none"};'
               f'endFill=1;endSize=9;strokeWidth=1.8;strokeColor={P[color]};'
               f'dashed={1 if dashed else 0};dashPattern=6 4;fontSize=23;fontFamily={self.font};'
               f'fontColor={P["ink"]};labelBackgroundColor=#FFFFFF;'
               f'exitX={exit[0]};exitY={exit[1]};exitDx=0;exitDy=0;'
               f'entryX={entry[0]};entryY={entry[1]};entryDx=0;entryDy=0;')
        e=ET.SubElement(self.root,'mxCell',id=ident,value=self.tr(en,zh),style=style,edge='1',parent='1',source=source,target=target)
        g=ET.SubElement(e,'mxGeometry',relative='1',attrib={'as':'geometry'})
        if label_dx or label_dy:
            ET.SubElement(g,'mxPoint',x=str(label_dx),y=str(label_dy),attrib={'as':'offset'})
        if points:
            a=ET.SubElement(g,'Array',attrib={'as':'points'})
            for x,y in points: ET.SubElement(a,'mxPoint',x=str(x),y=str(y))
        self.spec.append(dict(id=ident,role='edge',source=source,target=target,text=self.tr(en,zh),points=points or []))
        return ident

    def free_line(self,ident,x1,y1,x2,y2,color='line',dashed=False,arrow=False):
        e=ET.SubElement(self.root,'mxCell',id=f'{self.key}_line_{ident}',value='',edge='1',parent='1',
            style=f'edgeStyle=none;endArrow={"block" if arrow else "none"};endFill=1;strokeWidth=1.6;strokeColor={P[color]};dashed={int(dashed)};dashPattern=6 4;')
        g=ET.SubElement(e,'mxGeometry',relative='1',attrib={'as':'geometry'})
        ET.SubElement(g,'mxPoint',x=str(x1),y=str(y1),attrib={'as':'sourcePoint'})
        ET.SubElement(g,'mxPoint',x=str(x2),y=str(y2),attrib={'as':'targetPoint'})


def write_xml(path, diagrams):
    mx=ET.Element('mxfile',host='app.diagrams.net',modified='2026-11-19T00:00:00.000Z',
                  agent='Kinlin research architecture authoring',version='29.0.0',type='device',compressed='false')
    for diagram in diagrams:mx.append(diagram)
    ET.indent(mx,space='  ')
    ET.ElementTree(mx).write(path,encoding='utf-8',xml_declaration=True)


def validate(fig):
    ids={e.get('id') for e in fig.root}
    assert len(ids)==len(fig.root)
    for c in fig.root:
        if c.get('edge')=='1':
            for a in ['source','target']:
                if c.get(a):assert c.get(a) in ids,(fig.key,c.get('id'),a)
        g=c.find('mxGeometry')
        if c.get('vertex')=='1':
            x,y,w,h=[float(g.get(k,'0')) for k in ['x','y','width','height']]
            assert 0<=x<=x+w<=fig.w and 0<=y<=y+h<=fig.h,(fig.key,c.get('id'))
    boxes=[x for x in fig.spec if x['role']=='node' and x['w'] and x['h']]
    overlaps=[]
    for i,a in enumerate(boxes):
        for b in boxes[i+1:]:
            if min(a['x']+a['w'],b['x']+b['w'])>max(a['x'],b['x']) and min(a['y']+a['h'],b['y']+b['h'])>max(a['y'],b['y']):overlaps.append([a['id'],b['id']])
    assert not overlaps,overlaps
    return dict(figure=fig.key,language=fig.lang,vertices=len(ids)-2,semantic_nodes=len(boxes),
                edges=sum(e.get('edge')=='1' for e in fig.root),unique_ids=True,valid_edge_endpoints=True,
                vertices_inside_canvas=True,node_overlap_pairs=overlaps)

