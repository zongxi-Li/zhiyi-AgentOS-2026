"""Nine bilingual, native draw.io schematics for graph and skill evolution."""
from pathlib import Path
import json
from diagram_core import Figure, write_xml, validate

BASE=Path(__file__).resolve().parents[1]


def graph_loop(lang):
    f=Figure('g01','Evidence-governed graph evolution','证据驱动的图自进化架构',1440,920,lang)
    f.frame('offline','Offline graph evolution','离线图演化',40,110,1030,550,'blue')
    f.frame('authority','Release authority','正式发布权威',1110,110,290,730,'purple')
    ev=f.box('evidence','Deduplicated runs\nversions + outcomes','去重后的运行证据\n版本与真实验收',70,190,260,110)
    dg=f.box('diagnosis','Failure diagnosis\nsupport + counterevidence','重复失败诊断\n支持证据与反例',420,190,260,110)
    pt=f.box('patch','Bounded patch\nbase + digest','受限图补丁\n绑定基版本与摘要',770,190,260,110,'teal')
    va=f.box('static','Snapshot validation\ntypes / topology / access','图快照静态校验\n类型、拓扑与权限',770,430,260,110,'teal')
    rp=f.box('replay','Paired replay\nquality + total cost','同任务成对回放\n质量与完整成本',420,430,260,110,'teal')
    cf=f.box('confirm','Freeze + confirm\nfresh tasks / old abilities','冻结候选并独立确认\n新任务与历史能力',70,430,260,110,'teal')
    po=f.box('policy','Approved policy\ncurrent base version','已批准采纳策略\n当前基版本',1140,190,230,110,'gray')
    pu=f.box('publisher','Verify + CAS\ncompile + receipt','鉴权及基版本 CAS\n编译、提交与回执',1140,430,230,110,'purple',size=25)
    run=f.box('run','Future runs\npinned graph version','后续新运行\n固定图版本',1140,710,230,100)
    for k,a,b in [('evdg',ev,dg),('dgpt',dg,pt)]:f.edge(k,a,b)
    f.edge('ptva',pt,va,exit=(.5,1),entry=(.5,0))
    f.edge('varp',va,rp,exit=(0,.5),entry=(1,.5))
    f.edge('rpcf',rp,cf,exit=(0,.5),entry=(1,.5))
    f.edge('cfpu',cf,pu,exit=(.5,1),entry=(0,.5),points=[(200,610),(1090,610),(1090,485)])
    f.edge('policy',po,pu,dashed=True,exit=(.5,1),entry=(.5,0),color='purple')
    f.edge('run',pu,run,exit=(.5,1),entry=(.5,0))
    f.edge('feedback',run,ev,dashed=True,exit=(0,.5),entry=(0,.5),points=[(55,760),(55,245)])
    f.text('return','New verified outcomes become evidence for the next proposal','新运行的已核验结果，形成下一轮候选的证据',340,785,710,45,24)
    f.text('boundary','Candidates never edit an active run; failed or inconclusive proposals remain outside production.','候选不直接修改活跃运行；失败或证据不足的提案不进入生产版本',65,870,1310,35,23)
    return f


def graph_patch(lang):
    f=Figure('g02','A typed validator insertion patch','带类型约束的验证器插入补丁',1440,900,lang)
    f.frame('before','(a) G0: current execution DAG','(a) G0：当前执行依赖图',40,110,1360,230,'gray')
    a=f.box('a0','Input','输入',80,200,230,80)
    b=f.box('b0','Produce artifact','生成任务产物',530,200,260,80)
    c=f.box('c0','Continue','继续后续步骤',1130,200,230,80)
    f.edge('ab0',a,b);f.edge('bc0',b,c,'artifact','任务产物',label_dy=-22)
    f.frame('after','(b) G1: candidate with an explicit validation gate','(b) G1：加入显式验证门的候选图',40,395,1360,350,'teal')
    aa=f.box('a1','Input','输入',80,480,230,90)
    bb=f.box('b1','Produce artifact','生成任务产物',420,480,240,90)
    vv=f.box('v1','Registered validator\nvalidated artifact ref','已注册验证器\n产物通过验证的引用',760,480,260,90,'teal',size=25)
    cc=f.box('c1','Continue','继续后续步骤',1110,480,250,90)
    fail=f.box('fail','Stop / explicit recovery','终止或显式恢复',760,645,260,70,'orange',size=25)
    f.edge('ab1',aa,bb);f.edge('bv1',bb,vv)
    f.edge('vc1',vv,cc,'pass','通过',label_dy=-23)
    f.edge('vfail',vv,fail,'fail','不通过',color='orange',exit=(.5,1),entry=(.5,0),label_dx=62)
    f.text('contract','Patch binds base graph + step IDs + operator digest; recheck topology, I/O and side effects.','补丁绑定基图、步骤标识与算子摘要；重新校验拓扑、输入输出及副作用',65,785,1310,50,24)
    f.text('claim','Illustrative candidate; additional validation must earn its cost in independent task evaluation.','这是候选变更示例；新增验证的收益与成本仍需独立任务评测',65,850,1310,35,23)
    return f


def graph_semantics(lang):
    f=Figure('g03','Three graphs with different edge semantics','三类图的对象与边语义',1440,920,lang)
    for ident,en,zh,x,col in [('exec','Execution DAG','执行依赖图',40,'blue'),('search','Candidate lineage','候选版本血缘图',510,'purple'),('skill','Skill relations','技能关系图',980,'teal')]:
        f.frame(ident,en,zh,x,120,420,650,col)
    a=f.box('input','Input','输入',80,230,140,90,size=25)
    b=f.box('tool','Tool','工具',280,230,140,90,size=25)
    c=f.box('gate','Validate','验证',180,430,160,80,'blue',size=25)
    d=f.box('output','Output','输出',180,610,160,80,'blue',size=25)
    f.edge('exec1',a,b)
    f.edge('exec2',b,c,exit=(.5,1),entry=(.5,0),points=[(350,375),(260,375)])
    f.edge('exec3',c,d,exit=(.5,1),entry=(.5,0))
    p=f.box('v0','G₀','G₀',555,230,160,80,'purple')
    q=f.box('v1','G₁','G₁',555,430,160,80,'purple')
    r=f.box('v2','G₂','G₂',755,430,130,80,'purple')
    s=f.box('v3','G₃','G₃',650,610,160,80,'purple')
    f.edge('lineage1',p,q,exit=(.5,1),entry=(.5,0))
    f.edge('lineage2',p,r,exit=(1,.5),entry=(.5,0),points=[(820,270)])
    f.edge('lineage3',q,s,exit=(.5,1),entry=(.25,0),points=[(635,560),(690,560)])
    f.edge('lineage4',r,s,exit=(.5,1),entry=(.75,0),points=[(820,560),(770,560)])
    ex=f.box('extract','Extract@v2','抽取技能@v2',1040,230,280,80,'teal',size=25)
    va=f.box('validate','Validate@v1','核验技能@v1',1040,430,280,80,'teal',size=25)
    re=f.box('report','Report@v3','报告技能@v3',1040,610,280,80,'teal',size=25)
    f.edge('compose',ex,va,'compose_with','可组合',exit=(.5,1),entry=(.5,0),dashed=True,arrow=False,label_dx=90)
    f.edge('depends',re,va,'depend_on','依赖',exit=(.5,0),entry=(.5,1),label_dx=87)
    f.text('roles','Step order and data flow','步骤顺序与数据流',70,790,390,42,24)
    f.text('versions','Each node is a whole graph version','每个节点是完整图版本',530,790,420,42,24)
    f.text('relations','Relations do not schedule a run','关系本身不调度运行',1000,790,390,42,24)
    f.text('caveat','Lineage fusion is an optional research extension; it does not merge live executions.','血缘融合属于后续研究扩展，不等于合并正在执行的任务图',65,865,1310,35,23)
    return f


def graph_states(lang):
    f=Figure('g04','Proposal states and version-preserving rollback','图提案状态与保留历史的回滚',1440,1000,lang)
    names=[('draft','DRAFT','草案','blue'),('valid','VALIDATED','静态验证通过','teal'),('eval','EVALUATED','已完成选择评测','teal'),('confirm','CONFIRMED','独立确认通过','teal'),('publish','PUBLISHED','正式发布','purple')]
    ns=[f.box(k,en+'\n'+zh if lang=='zh' else en,en+'\n'+zh,70+270*i,210,220,100,col,size=25) for i,(k,en,zh,col) in enumerate(names)]
    for i in range(4):f.edge('normal'+str(i),ns[i],ns[i+1])
    rej=f.box('reject','REJECTED\nfailed gate','REJECTED\n明确未通过门槛',70,500,350,105,'orange')
    inc=f.box('inconclusive','INCONCLUSIVE\ninsufficient evidence','INCONCLUSIVE\n证据不足',550,500,350,105,'orange')
    stale=f.box('stale','STALE\nbase / dependency drift','STALE\n基版本或依赖已变化',1030,500,350,105,'orange')
    f.edge('reject',ns[1],rej,exit=(.5,1),entry=(.5,0),color='orange',points=[(450,420),(245,420)])
    f.edge('inc',ns[2],inc,exit=(.5,1),entry=(.5,0),color='orange',points=[(720,450),(725,450)])
    f.edge('stale',ns[3],stale,exit=(.5,1),entry=(.5,0),color='orange',points=[(990,420),(1205,420)])
    f.text('gate','Release rechecks authenticated approval, report binding and base-version CAS.','发布时重验真实审批、报告绑定与基版本 CAS；不是仅凭 CONFIRMED 字段放行',65,650,1310,45,24)
    f.text('rollbackheading','Rollback is a new authorized release','回滚也是一次新的授权发布',65,730,1310,40,27,True)
    old=f.box('old','Published Gₖ','已发布 Gₖ',70,805,300,90,'purple')
    new=f.box('proposal','New proposal\nknown-good content','新回滚提案\n引用已知良好内容',520,805,400,90,'teal')
    nxt=f.box('next','New version Gₖ₊₁','生成新版本 Gₖ₊₁',1100,805,270,90,'purple')
    f.edge('rollback1',old,new);f.edge('rollback2',new,nxt)
    f.text('footer','Revalidate compatibility; retain history and pinned runs; never roll back the privacy ledger.','重新验证兼容性；保留历史及运行快照；隐私消费账本永不随之回滚',65,940,1310,35,23)
    return f


def skill_loop(lang):
    f=Figure('s01','From execution evidence to reusable skills','从执行证据到可复用 Skills',1440,940,lang)
    f.frame('abstract','Evidence and abstraction','证据与技能抽象',40,120,1360,280,'blue')
    ev=f.box('evidence','Successes + failures\nverified outcomes','成功与失败轨迹\n可核验的任务结果',70,210,330,110)
    ab=f.box('abstractor','Infer stable structure\nslots + applicability','归纳稳定可复用结构\n变量槽位与适用边界',555,210,330,110)
    ca=f.box('candidate','ADD / PATCH\nimmutable package digest','ADD / PATCH 候选\n绑定不可变技能包摘要',1040,210,330,110,'teal')
    f.edge('evab',ev,ab);f.edge('abca',ab,ca)
    f.frame('assess','Validation, evaluation and publication','校验、评测与正式发布',40,500,1360,270,'teal')
    va=f.box('validate','Validate package\nschema + program tests','技能包校验\n合同、程序与依赖测试',1040,590,330,110,'teal')
    co=f.box('compare','Compare + confirm\nfixed context / fresh tasks','对照评测与独立确认\n固定上下文、新确认任务',555,590,330,110,'teal')
    pu=f.box('publish','Registry publication\npermission + CAS','发布至正式注册表\n权限核验与 CAS',70,590,330,110,'purple')
    f.edge('cava',ca,va,exit=(.5,1),entry=(.5,0))
    f.edge('vaco',va,co,exit=(0,.5),entry=(1,.5))
    f.edge('copu',co,pu,exit=(0,.5),entry=(1,.5))
    use=f.box('future','Future runs retrieve approved immutable versions; source documents never grant execution authority.','后续运行检索已批准的不可变版本；来源文档本身不授予执行权限',70,815,1300,65,'gray',size=24)
    f.edge('use',pu,use,exit=(.5,1),entry=(.5,0),points=[(235,790),(720,790)])
    f.text('footer','External skill evolution first; model-weight training remains a separate, later research path.','优先研究外部技能演化；模型权重训练是独立且后置的研究路径',65,900,1310,30,23)
    return f


def skill_runtime(lang):
    f=Figure('s02','Immutable skill packages and runtime retrieval','不可变技能包与运行时检索数据流',1440,940,lang)
    f.frame('package','Immutable skill package','不可变技能包',40,110,480,700,'purple')
    f.frame('runtime','Version-filtered retrieval and execution','按版本过滤的检索与执行',580,110,820,700,'blue')
    ident=f.box('identity','Identity + provenance\nskillId / version / digest','身份、版本与来源\nskillId / version / digest',65,190,430,105,'purple')
    f.box('contract','Contract + limits\ninputs / slots / failure modes','合同与边界\n输入、槽位及失效条件',65,350,430,105,'purple')
    f.box('resources','Procedure + resources\nsteps / scripts / dependencies','步骤、程序与资源\n脚本、依赖和资源摘要',65,510,430,105,'purple')
    f.box('evidence','Verified evidence\nreports / counterexamples','核验证据\n评测报告与已知反例',65,670,430,105,'purple')
    req=f.box('request','Task + run snapshot','任务及运行版本快照',620,190,320,95)
    recall=f.box('recall','Hybrid retrieval\nkeywords + embeddings','混合召回\n关键词与语义向量',1030,190,330,95)
    filt=f.box('filter','Contract / access filter\ncompatible versions only','合同、权限与依赖过滤\n仅保留兼容版本',1030,380,330,95,'teal',size=25)
    rank=f.box('rank','Rerank + token budget','重排及上下文预算',620,380,320,95,'teal',size=25)
    bind=f.box('bind','Pin exact skill versions','绑定精确技能版本',620,570,320,95,'purple',size=25)
    exe=f.box('execute','Invoke + verify outcome','调用并核验任务结果',1030,570,330,95,'blue',size=25)
    usage=f.box('usage','retrieved → injected → invoked → verified','召回 → 注入 → 调用 → 结果核验',620,735,740,60,'gray',size=24)
    f.edge('request',req,recall)
    f.edge('filter',recall,filt,exit=(.5,1),entry=(.5,0))
    f.edge('rank',filt,rank,exit=(0,.5),entry=(1,.5))
    f.edge('bind',rank,bind,exit=(.5,1),entry=(.5,0))
    f.edge('execute',bind,exe)
    f.edge('usage',exe,usage,exit=(.5,1),entry=(.5,0),points=[(1195,705),(990,705)])
    f.edge('index',ident,recall,dashed=True,color='purple',exit=(1,.5),entry=(.5,0),points=[(550,242.5),(550,170),(1195,170)])
    f.text('footer1','Indexes derive from package metadata; the run snapshot limits eligible versions and capabilities.','索引由技能元数据构建；运行快照约束可用版本及能力权限',65,850,1310,35,23)
    f.text('footer2','Retrieval is not usage, and usage is not proof of contribution.','被召回不等于被使用，被使用不等于已证明贡献',65,900,1310,30,23)
    return f


def skill_evaluation(lang):
    f=Figure('s03','Controlled evaluation of a skill update','技能更新的受控贡献评估',1440,940,lang)
    ctx=f.box('context','Freeze graph, model, tools, retriever and environment; predeclare sampling and evaluation rules.','固定图、模型、工具、检索器及环境；预先约定采样与评测规则',70,115,1300,85,'gray',size=25)
    task=f.box('tasks','Selection task set\npaired task IDs\nplanned repetitions','选择任务集\n同任务成对比较\n预定重复次数',70,295,260,150)
    arms=[]
    for k,en,zh,y,col in [('none','No target skill\nmatched context budget','不注入目标技能\n对齐上下文预算',240,'gray'),('base','Base skill S₀\nfixed graph G₀','原技能 S₀\n固定图 G₀',410,'blue'),('new','Candidate skill S₁\nfixed graph G₀','候选技能 S₁\n固定图 G₀',580,'teal')]:
        arms.append(f.box(k,en,zh,485,y,345,100,col,size=25))
    out=f.box('outcomes','Paired outcomes\nquality / cost / misuse','成对评测结果\n质量、成本与误用',1100,410,270,110,'teal',size=25)
    for i,(arm,y) in enumerate(zip(arms,[290,460,630])):
        f.edge('input'+str(i),task,arm,points=[(410,370),(410,y)])
        f.edge('output'+str(i),arm,out,entry=(0,[.2,.5,.8][i]),points=[(950,y),(950,432+33*i)])
    f.edge('context',ctx,task,dashed=True,exit=(.5,1),entry=(.5,0),points=[(720,220),(200,220)])
    fresh=f.box('fresh','Fresh confirmatory task set\nseparate content lineage and time','新鲜的独立确认任务\n按内容血缘及时间隔离',70,760,850,90,'purple',size=25)
    conf=f.box('confirm','Freeze → confirm\nnew task split','冻结候选后确认\n使用独立任务',1100,760,270,90,'teal',size=25)
    f.edge('fresh',fresh,conf)
    f.edge('confirm',out,conf,exit=(.5,1),entry=(.5,0))
    f.text('footer','Joint search: compare G₀S₀, G₁S₀, G₀S₁ and G₁S₁; shared reward is not causal attribution.','联合搜索比较 G₀S₀、G₁S₀、G₀S₁、G₁S₁；共同成功奖励不等于因果归因',65,890,1310,35,23)
    return f


def skill_lifecycle(lang):
    f=Figure('s04','Skill lifecycle and orthogonal retrieval policy','Skills 生命周期与独立的召回策略',1440,950,lang)
    cand=f.box('candidate','candidate','candidate\n候选版本',100,210,240,110,'blue')
    ver=f.box('verified','verified','verified\n已验证版本',430,210,260,110,'teal')
    dep=f.box('deprecated','deprecated','deprecated\n停止默认推荐',790,210,240,110,'gray')
    ret=f.box('retired','retired','retired\n退役并保留历史',1120,210,240,110,'gray')
    for k,a,b in [('verify',cand,ver),('deprecate',ver,dep),('retire',dep,ret)]:f.edge(k,a,b)
    f.edge('newversion',ver,cand,'new candidate version','新建候选版本',dashed=True,exit=(.5,0),entry=(.5,0),points=[(560,140),(220,140)],label_dy=-22)
    arch=f.box('archive','Exploration archive\nrejected / inconclusive','探索档案\n拒绝或证据不足',75,500,340,110,'orange')
    index=f.box('retrieval','Retrieval policy (orthogonal)\nACTIVE ↔ DORMANT\nprotect rare capabilities','独立于质量状态的召回策略\nACTIVE ↔ DORMANT\n保护稀有能力',455,500,480,140,'purple',size=25)
    history=f.box('history','Retain history\npinned references','保留历史版本\n保留运行绑定引用',1120,500,240,110,'purple',size=25)
    f.edge('archive',cand,arch,exit=(.5,1),entry=(.5,0),points=[(220,450),(245,450)],color='orange')
    f.edge('index',ver,index,dashed=True,exit=(.5,1),entry=(.5,0),points=[(560,420),(695,420)],color='purple')
    f.edge('history',ret,history,dashed=True,exit=(.5,1),entry=(.5,0),color='purple')
    f.box('impact','Dependency change: recheck affected graphs before adopting a new version\nRetirement ends default discovery; historical runs keep their exact references','依赖或合同变化：采用新版本前重新检查受影响的图\n退役停止默认发现；历史运行保留精确引用',70,740,1300,110,'gray',size=25)
    f.text('footer','Low usage does not establish low value; dormant is a retrieval mode, not a quality verdict.','低频不等于低价值；dormant 是召回模式，不是质量判决',65,895,1310,35,23)
    return f


def joint_release(lang):
    f=Figure('j01','Coherent graph–skill release through a manifest','通过版本清单一致发布图与 Skills',1440,1060,lang)
    gp=f.box('graph','Graph proposal\nbase graph + candidate digest','图更新提案\n基图与候选内容摘要',70,135,540,120,'blue')
    sp=f.box('skill','Skill proposal\nbase skill + candidate digest','技能更新提案\n基技能与候选内容摘要',830,135,540,120,'teal')
    report=f.box('report','Independent evaluation\ncandidate / data / dependency digests','独立评测与确认材料\n候选、数据及依赖摘要',450,350,540,110,'teal',size=25)
    f.edge('graphreport',gp,report,exit=(.5,1),entry=(.25,0),points=[(340,300),(585,300)])
    f.edge('skillreport',sp,report,exit=(.5,1),entry=(.75,0),points=[(1100,300),(855,300)])
    stage=f.box('stage','Stage immutable artifacts\ncompiled graph + skills','暂存不可变制品\n已编译图与技能包',70,570,330,110,'purple',size=25)
    cas=f.box('cas','Verify bindings + auth\nCAS release manifest','核验内容绑定及权限\nCAS 发布版本清单',550,570,340,110,'purple',size=25)
    manifest=f.box('manifest','Active manifest Mₖ₊₁\nall pinned versions','活跃清单 Mₖ₊₁\n精确绑定全部版本',1040,570,330,110,'purple',size=25)
    f.edge('stage',report,stage,exit=(0,.5),entry=(.5,0),points=[(235,405)])
    f.edge('reportcas',report,cas,exit=(.5,1),entry=(.5,0))
    f.edge('stagecas',stage,cas);f.edge('casmanifest',cas,manifest)
    f.frame('snapshots','Execution snapshots','执行快照',500,760,900,220,'blue')
    old=f.box('old','Existing run snapshot\nkeeps Mₖ','已有运行快照\n继续绑定 Mₖ',550,825,340,110,'blue',size=25)
    new=f.box('new','New run snapshot\nresolve exact versions','新运行快照\n解析并固定精确版本',1040,825,330,110,'blue',size=25)
    f.edge('newrun',manifest,new,exit=(.5,1),entry=(.5,0))
    rb=f.box('rollback','Rollback as Mₖ₊₂\nknown-good references','回滚生成 Mₖ₊₂\n引用已知良好制品',70,825,330,110,'orange',size=25)
    f.edge('rollback',rb,cas,exit=(1,.5),entry=(.5,1),points=[(460,880),(460,735),(720,735)],color='orange')
    f.text('footer','One atomic manifest pointer; stores may be separate. Privacy consumption remains independent.','仅版本清单指针原子切换；制品存储可分离；隐私消费账本独立且不回滚',65,1005,1310,35,23)
    return f


BUILDERS=[graph_loop,graph_patch,graph_semantics,graph_states,skill_loop,skill_runtime,skill_evaluation,skill_lifecycle,joint_release]
GROUPS={'Graph_Evolution':['g01','g02','g03','g04'],'Skills_Evolution':['s01','s02','s03','s04'],'Joint_Release':['j01']}


def main():
    for directory in ['drawio','svg','pdf','png','.build']: (BASE/directory).mkdir(exist_ok=True)
    manifest=[];checks=[]
    for lang in ['en','zh']:
        figs=[builder(lang) for builder in BUILDERS]
        for f in figs:
            path=BASE/'drawio'/f'{f.key}_{lang}.drawio'
            write_xml(path,[f.diagram]); checks.append(validate(f))
            manifest.append(dict(key=f.key,lang=lang,name=f.name,width=f.w,height=f.h,path=path.relative_to(BASE).as_posix(),spec=f.spec))
        for group,keys in {**GROUPS,'Evolution_All_Figures':[f.key for f in figs]}.items():
            write_xml(BASE/'drawio'/f'{group}_{lang}.drawio',[f.diagram for f in figs if f.key in keys])
    (BASE/'.build/figures.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (BASE/'.build/xml-validation.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
    (BASE/'.build/groups.json').write_text(json.dumps(GROUPS,indent=2),encoding='utf-8')
    print(f'Authored {len(manifest)} native figures; structural checks passed.')


if __name__=='__main__':main()
