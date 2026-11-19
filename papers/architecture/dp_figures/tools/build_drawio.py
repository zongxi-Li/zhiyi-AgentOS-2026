"""Author bilingual, editable DP schematics as uncompressed draw.io XML."""
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


def architecture(lang):
    f=Figure('fig01','Local privacy release architecture','本地隐私发布架构',1440,850,lang)
    f.frame('client','Trusted client','可信本机',40,100,1060,610,'blue')
    f.frame('cloud','Remote observer','云端观察者',1140,100,260,610,'gray',True)
    a=f.box('input','Private input\nx','私有输入\nx',70,190,190,110)
    b=f.box('prefix','Local prefix\n+ private KV','本地前导网络\n及私有 KV',310,190,220,110)
    c=f.box('gate','Privacy release gate\nclip, randomize, bind','隐私发布门\n裁剪、随机化、绑定',590,190,270,110,'teal')
    d=f.box('egress','Approved\npayload','批准的\n唯一载荷',910,190,160,110,'teal')
    e=f.box('suffix','Suffix + KV\nand output head','云端后段、KV\n及输出头',1165,190,210,110,'gray')
    for i,(s,t) in enumerate([(a,b),(b,c),(c,d),(d,e)]):f.edge(str(i),s,t)
    p=f.box('profile','Approved profile\nneighbor / protocol / mechanism','已批准的隐私合同\n邻接、协议、机制',70,420,280,125,'gray')
    l=f.box('ledger','Persistent ledger\nRDP + atomic reservation','持久预算账本\nRDP 与原子预留',400,420,290,125,'purple')
    o=f.box('outbox','Durable outbox\nreleaseId ↔ exact bytes','持久载荷发件箱\n发布标识绑定唯一字节',740,420,330,125,'purple')
    f.edge('profile',p,c,'control','控制',dashed=True,exit=(.5,0),entry=(.25,1),points=[(210,360),(658,360)],label_dy=-17)
    f.edge('budget',l,c,'reserve first','先预留',color='purple',dashed=True,exit=(.5,0),entry=(.5,1),points=[(545,380),(725,380)],label_dy=18)
    f.edge('durable',c,o,'persist before send','先持久化再发送',color='purple',dashed=True,exit=(1,.8),entry=(.5,0),points=[(890,278),(890,365),(905,365)],label_dx=55)
    r=f.box('receipt','Step result\n+ commit receipt','步骤结果\n及提交回执',1165,420,210,125,'gray')
    f.edge('reply',e,r,'receipt','回执',dashed=True,exit=(.5,1),entry=(.5,0),label_dx=52)
    f.edge('feedback',r,b,'verify locally; next step','本地核验后进入下一步',dashed=True,exit=(.5,1),entry=(.5,0),points=[(1270,640),(55,640),(55,160),(420,160)],label_dx=250,label_dy=20)
    f.text('scope','Public-shape protocol; content protection within the declared input domain','公开固定形状协议；仅在声明的输入域和保护范围内讨论内容隐私',70,735,1300,40,24)
    f.text('key','Solid: payload flow     Dashed: control / response     Purple: persistent state','实线：载荷数据流     虚线：控制或返回     紫色：持久状态',70,790,1300,35,23)
    return f


def pipeline(lang):
    f=Figure('fig02','Write-ahead release dataflow','先记账、后发送的发布数据流',1440,850,lang)
    x=[70,425,780,1135];w=235;h=120
    vals=[
      ('validate','1  Validate profile\nidentity + protocol','1  校验发布合同\n身份与公开协议','gray'),
      ('reserve','2  Reserve once\natomic transaction','2  去重并预留预算\n账户内原子事务','purple'),
      ('noise','3  Clip + randomize\none noise draw','3  裁剪并随机化\n只产生一个新样本','teal'),
      ('prepare','4  Persist bytes\nPREPARED','4  持久化唯一字节\nPREPARED','purple'),
    ]
    top=[f.box(k,en,zh,x[i],160,w,h,col,size=25) for i,(k,en,zh,col) in enumerate(vals)]
    for i in range(3):f.edge(f'top{i}',top[i],top[i+1])
    vals2=[
      ('finish','8  Record ACKED\nno second charge','8  记录 ACKED\n不再次扣费','purple'),
      ('verify','7  Verify receipt\nstep + digest','7  核验步骤回执\n请求、步骤、摘要','blue'),
      ('send','6  Send payload\nexact bytes + TLS','6  发送批准载荷\n经认证的传输通道','gray'),
      ('mark','5  Mark durable\nMAYBE_SENT','5  持久化发送标记\nMAYBE_SENT','purple'),
    ]
    bottom=[f.box(k,en,zh,x[i],450,w,h,col,size=25) for i,(k,en,zh,col) in enumerate(vals2)]
    f.edge('turn',top[3],bottom[3],exit=(.5,1),entry=(.5,0))
    for i in [3,2,1]:f.edge(f'bottom{i}',bottom[i],bottom[i-1],exit=(0,.5),entry=(1,.5))
    f.text('gap','The only network send occurs after both durable budget and payload binding','网络发送必须晚于预算持久预留与唯一载荷持久绑定',85,335,1220,65,26,True,'teal')
    f.box('retry','Duplicate releaseId: verify binding and follow recovery; do not reserve or sample again','重复发布标识：核对绑定后进入恢复流程，不再次预留，也不重新采样',70,650,1300,75,'gray',size=25)
    f.text('failure','Any failure before step 6 blocks sending. Unknown egress retains its charge (Figures 3 and 5).','第 6 步前任一环节失败均阻止发送；未知出站保留已计费用，见图 3 与图 5',70,760,1300,55,23)
    return f


def states(lang):
    f=Figure('fig03','Persistent release state machine','持久隐私发布状态机',1440,850,lang)
    n=f.box('new','NEW\nuncharged','NEW\n尚未预留',55,190,170,100,'gray',shape='ellipse')
    r=f.box('reserved','RESERVED\ncharge reserved','RESERVED\n费用已预留',290,190,240,100,'purple')
    p=f.box('prepared','PREPARED\nexact bytes durable','PREPARED\n唯一载荷已持久化',600,190,240,100,'purple')
    m=f.box('maybe','MAYBE_SENT\negress permitted','MAYBE_SENT\n允许开始发送',910,190,240,100,'purple')
    a=f.box('acked','ACKED\nreceipt verified','ACKED\n回执已核验',1210,190,180,100,'blue')
    f.edge('reserve',n,r,'admit','预留',label_dy=-24)
    f.edge('prepare',r,p,'bind','绑定',label_dy=-24)
    f.edge('mark',p,m,'log','标记',label_dy=-24)
    f.edge('ack',m,a,'ACK','回执',label_dy=-24)
    seal=f.box('sealed','SEALED_CHARGED\nno further send / no refund','SEALED_CHARGED\n不再发送，费用不退回',505,540,430,105,'orange')
    f.edge('orphan',r,seal,'unrecoverable crash','不可恢复崩溃',color='orange',exit=(.5,1),entry=(0,.5),points=[(410,592)],label_dx=-25,label_dy=5)
    f.edge('badbytes',p,seal,'bytes lost / cancel','载荷丢失或取消',color='orange',exit=(.5,1),entry=(.5,0),label_dx=115)
    f.edge('unknown',m,seal,'cannot recover safely','无法安全恢复',color='orange',exit=(.5,1),entry=(1,.5),points=[(1030,592)],label_dx=50)
    f.edge('retry',m,m,'recover first; same bytes only','先核查恢复条件，仅重用原字节',dashed=True,exit=(.75,0),entry=(.25,0),points=[(1090,110),(970,110)],label_dy=-24)
    f.text('query','ACKED duplicates return the original receipt. Missing bytes never authorize resampling.','ACKED 的重复请求返回原回执；载荷缺失永远不构成重新采样的授权',65,677,1300,55,24)
    f.text('meaning','SEALED_CHARGED is an internal terminal marker; remote state may remain unknown.','SEALED_CHARGED 是本地终止标记，并不证明云端从未接收或从未执行',65,735,1300,55,24)
    f.text('budget','Conservative first version: all reservations remain charged; state transitions do not add the fee again.','初版采取保守记账：所有预留均保留费用，后续状态迁移不重复计费',65,795,1300,35,23)
    return f


def accounting(lang):
    f=Figure('fig04','Gaussian release and prospective composition','Gaussian 发布与前瞻组合会计',1440,940,lang)
    f.text('a','(a) One complete publication vector','(a) 一次完整发布向量',50,100,1320,40,27,True)
    h=f.box('h','Local activation\nh(x) ∈ Rᵈ','本地激活\nh(x) ∈ Rᵈ',65,175,230,110)
    cl=f.box('clip','Global L2 clipping\n‖h̄(x)‖₂ ≤ C','全局 L2 裁剪\n‖h̄(x)‖₂ ≤ C',365,175,290,110,'teal')
    no=f.box('gaussian','Gaussian noise\nZ ∼ N(0, s²I)','Gaussian 噪声\nZ ∼ N(0, s²I)',725,175,290,110,'teal')
    yy=f.box('y','Release\nY = h̄(x) + Z','发布载荷\nY = h̄(x) + Z',1085,175,290,110,'gray')
    f.edge('hc',h,cl);f.edge('cn',cl,no);f.edge('ny',no,yy)
    f.text('sensitivity','Prompt replacement: Δ₂ ≤ 2C. Noise calibration and finite-precision implementation require review.','prompt replacement 邻接：Δ₂ ≤ 2C；噪声校准与有限精度实现必须另行核查',65,315,1300,65,24)
    f.text('b','(b) Prospective check before atomic reservation','(b) 原子预留前检查累计上界',50,425,1320,40,27,True)
    rr=f.box('rho','Charged account R(α)\nincludes reservations','账户已计费用 R(α)\n包含全部预留',65,490,500,100,'purple')
    ct=f.box('cost','Public-schedule cost cₜ(α)\n= αΔₜ² / (2sₜ²)','公开调度费用 cₜ(α)\n= αΔₜ² / (2sₜ²)',65,640,500,100,'purple')
    eps=f.box('convert','Prospective ε at fixed δ*\nminα {R(α) + cₜ(α)\n+ ln(1/δ*) / (α − 1)}','固定 δ* 下的前瞻 ε\nminα {R(α) + cₜ(α)\n+ ln(1/δ*) / (α − 1)}',700,530,675,150,'purple',size=25)
    f.edge('account',rr,eps,exit=(1,.5),entry=(0,.3),points=[(635,540),(635,575)])
    f.edge('cost',ct,eps,exit=(1,.5),entry=(0,.7),points=[(635,690),(635,635)])
    yes=f.box('accept','Within ε limit: reserve atomically\nR(α) ← R(α) + cₜ(α)','满足 ε 上限：原子预留\nR(α) ← R(α) + cₜ(α)',700,770,675,90,'teal')
    deny=f.box('deny','Over limit / incompatible account\nreject without sending','超出预算或会计不兼容\n拒绝发布',65,790,500,70,'orange',size=24)
    f.edge('accept',eps,yes,'pass','通过',exit=(.75,1),entry=(.75,0),label_dx=45)
    f.edge('deny',eps,deny,'fail','不通过',color='orange',exit=(.15,1),entry=(.5,0),points=[(801,760),(315,760)],label_dy=2)
    f.text('scope','Fixed public cost schedule; conditional bounds; no subsampling amplification.','固定公开费用调度；同一保护范围内的条件上界；不使用子采样放大',65,890,1300,35,23)
    return f


def sequence(lang):
    f=Figure('fig05','Lost-receipt recovery without resampling','不重采样的丢失回执恢复时序',1440,1060,lang)
    xs=[170,535,900,1265]
    heads=[('Local runtime','本地 Runtime','blue'),('Release gate / outbox','发布门与发件箱','teal'),('Privacy ledger','隐私账本','purple'),('Cloud / suffix KV','云端后段与 KV','gray')]
    anchors=[]
    for i,(en,zh,col) in enumerate(heads):
        f.box(f'actor{i}',en,zh,xs[i]-145,105,290,65,col,size=26,bold=True)
        f.free_line(f'life{i}',xs[i],180,xs[i],825,'gray',True)
    def msg(k,a,b,y,en,zh,dash=False,color='line'):
        # Invisible, zero-area endpoint cells keep messages natively editable.
        s=f.box(f'{k}s','','',xs[a],y,0,0,'gray',fill='none',stroke='none',role='anchor')
        t=f.box(f'{k}t','','',xs[b],y,0,0,'gray',fill='none',stroke='none',role='anchor')
        f.edge(k,s,t,en,zh,dashed=dash,color=color,label_dy=-21)
    msg('request',0,1,220,'activation reference','激活引用')
    msg('reserve',1,2,280,'reserve once','只预留一次')
    msg('reserved',2,1,340,'reservation receipt','预留凭据',True,'purple')
    f.box('localwork','Sample once; persist bytes + MAYBE_SENT','采样一次；持久化载荷\n再写可能出站状态',380,380,310,85,'teal',size=24)
    msg('payload',1,3,505,'exact prepared payload','已固化的唯一载荷')
    f.box('cloudwork','Serialized step commit\nKV + token + receipt','串行化步骤提交\nKV、token 与回执',1110,535,310,80,'gray',size=24)
    msg('lost',3,1,650,'reply lost / timeout','回执丢失或超时',True,'orange')
    msg('query',1,3,720,'query authoritative step state','查询权威步骤状态',True)
    msg('status',3,1,790,'COMMITTED / NOT_COMMITTED / UNKNOWN','已提交 / 确定未提交 / 不确定',True)
    f.box('committed','COMMITTED\nreuse receipt; advance once','已提交\n复用回执，只推进一次',45,880,420,110,'blue',size=25)
    f.box('notcommitted','NOT_COMMITTED\nretry identical bytes only','确定未提交\n仅允许重发相同字节',510,880,420,110,'teal',size=25)
    f.box('unknown','UNKNOWN / session invalid\nstop; retain charge','状态不确定或会话失效\n停止，保留消费',975,880,420,110,'orange',size=25)
    f.text('authority','NOT_COMMITTED must exclude in-flight work under the same session lock; an empty lookup is insufficient.','“确定未提交”必须在会话串行控制下排除在途执行；普通查询为空并不足以证明',45,1010,1350,35,23)
    return f


def protocol(lang):
    f=Figure('fig06','Protocol observability and enforcement','协议可观测范围与发布约束',1440,940,lang)
    f.frame('private','Private local state','本地私有状态',40,110,400,590,'blue')
    f.frame('enforce','Protocol enforcement','批准协议的强制执行',510,110,420,590,'teal')
    f.frame('observed','Remote observation','云端可观测内容',1000,110,400,590,'gray')
    a=f.box('act','Activation values\nprivate-input dependent','激活数值\n依赖私有输入',65,205,350,100)
    b=f.box('random','Clip + randomize\ncomplete vector','裁剪并随机化\n作用于完整向量',535,205,370,100,'teal')
    c=f.box('tensor','Randomized tensor Y','随机化张量 Y',1025,205,350,100,'gray')
    d=f.box('length','True length / mask\nprivate position data','真实长度、mask\n私有位置数据',65,375,350,100)
    e=f.box('public','Public shape / padding\nallowlisted metadata','公开形状与 padding\n元数据白名单',535,375,370,100,'teal')
    g=f.box('meta','Declared public metadata','声明为公开的元数据',1025,375,350,100,'gray')
    h=f.box('behavior','Stop / error / timing\nprivate-state dependent','停止、错误与时序\n可能依赖私有状态',65,545,350,100)
    j=f.box('schedule','Approved schedule / rules\notherwise revise scope','批准的调度与规则\n否则重新界定保护范围',535,545,370,100,'teal')
    k=f.box('trace','Observable interaction trace','可观测交互记录',1025,545,350,100,'gray')
    for key,s,t in [('ab',a,b),('bc',b,c),('de',d,e),('eg',e,g),('hj',h,j),('jk',j,k)]:f.edge(key,s,t)
    reject=f.box('reject','Unapproved raw fields or behavior: block remote release\nno raw-text fallback; no guarantee for an unanalyzed channel','未经批准的原始字段或行为：阻止远程发布\n不降级发送原文，不为未分析的通道作保证',125,755,1190,85,'orange',size=25)
    f.text('scope','Scope must state public identity / participation and any excluded timing or side channels explicitly.','保护范围必须明确身份与参与信息是否公开，以及是否排除时序或其他侧信道',65,870,1310,45,24)
    return f


BUILDERS=[architecture,pipeline,states,accounting,sequence,protocol]


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


def main():
    for directory in ['drawio','svg','pdf','png','.build']: (BASE/directory).mkdir(exist_ok=True)
    out=BASE/'drawio'
    manifest=[];report=[]
    for lang in ['en','zh']:
        figs=[builder(lang) for builder in BUILDERS]
        for f in figs:
            path=out/f'{f.key}_{lang}.drawio'
            write_xml(path,[f.diagram])
            report.append(validate(f))
            manifest.append(dict(key=f.key,lang=lang,name=f.name,width=f.w,height=f.h,
                                 path=path.relative_to(BASE).as_posix(),spec=f.spec))
        write_xml(out/f'DP_Paper_Figures_{lang}.drawio',[f.diagram for f in figs])
    (BASE/'.build/figures.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (BASE/'.build/xml-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
