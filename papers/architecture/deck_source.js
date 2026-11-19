await artifactSession.run(async ({ presentation, session }) => {
  presentation.slides.delete(presentation.slides.items.map(s=>s.id));
  presentation.theme.defaultFont = "Microsoft YaHei";
  const C={ink:"#182B35",muted:"#52626E",teal:"#007F85",green:"#3F735B",orange:"#A35D35",pale:"#EDF5F5",line:"#91A9AF",white:"#FFFFFF",gray:"#F3F6F7"};
  const text=(s,n,t,x,y,w,h,size=25,color=C.ink,bold=false,align="left")=>{
    const a=s.shapes.add({geometry:"textbox",name:n,position:{left:x,top:y,width:w,height:h},fill:"none",line:{fill:"none",width:0}});
    a.text=t;a.text.style={fontSize:size,typeface:"Microsoft YaHei",color,bold,alignment:align,verticalAlignment:"middle",insets:0,autoFit:"none",wrap:"square"};return a;
  };
  const node=(s,n,t,x,y,w,h,fill=C.gray,color=C.ink)=>{
    const a=s.shapes.add({geometry:"rect",name:n,position:{left:x,top:y,width:w,height:h},fill,line:{fill:C.line,width:1.4}});
    a.text=t;a.text.style={fontSize:25,typeface:"Microsoft YaHei",color,bold:true,alignment:"center",verticalAlignment:"middle",insets:12,autoFit:"none",wrap:"square"};return a;
  };
  const link=(s,a,b,from="right",to="left",dash=false,color=C.teal)=>s.shapes.connect(a,b,{kind:a.position.top===b.position.top?"straight":"elbow",fromSide:from,toSide:to,line:{fill:color,width:2.6,style:dash?"dashed":"solid"},tail:{type:"arrow",width:"med",length:"med"}});
  const segment=(s,n,x,y,w,h,head=false,tail=false,color=C.teal,dash=false)=>s.shapes.add({geometry:"connector",name:n,kind:"straight",position:{left:x,top:y,width:w,height:h},line:{fill:color,width:2.4,style:dash?"dashed":"solid"},head:{type:head?"arrow":"none"},tail:{type:tail?"arrow":"none"}});
  const page=(title,subtitle,num)=>{
    const s=presentation.slides.add();s.size={width:1600,height:900};s.background.fill=C.white;
    text(s,"title",title,70,45,1440,76,46,C.ink,true);
    text(s,"subtitle",subtitle,70,125,1450,52,26,C.muted);
    text(s,"page",num+" / 3",1440,825,90,32,20,C.muted,false,"right");return s;
  };
  const s1=page("差分隐私：本地发布与预算事务","保护对象、组合会计和持久载荷共同决定外发边界",1);
  text(s1,"local-trust","可信本机",70,206,1040,36,25,C.teal,true);
  text(s1,"cloud-trust","云端观察者",1320,206,230,36,25,C.muted,true);
  const a=node(s1,"activation","前段激活\n公开固定形状",70,280,210,135);
  const b=node(s1,"contract","发布合同\n邻接 / 敏感度",340,280,210,135);
  const c=node(s1,"mechanism","裁剪与加噪\nGaussian",610,280,210,135,C.pale);
  const d=node(s1,"outbox","载荷固化\nOutbox",880,280,220,135,C.pale);
  const e=node(s1,"cloud","云端后段\n处理批准载荷",1320,280,210,135);
  link(s1,a,b);link(s1,b,c);link(s1,c,d);link(s1,d,e);
  text(s1,"send-label","认证发送",1130,290,160,40,22,C.teal,false,"center");
  segment(s1,"trust-boundary",1270,220,0,435,false,false,C.line,true);
  const ledger=node(s1,"ledger","Privacy Ledger\n跨会话组合会计 / 原子预算预留",340,530,480,110);
  const bytes=node(s1,"persistent-payload","releaseId 唯一\n原字节持久化",880,530,220,110);
  link(s1,ledger,c,"top","bottom");link(s1,d,bytes,"bottom","top");
  text(s1,"reserve-order","先预留",590,482,130,35,22,C.teal);
  text(s1,"store-order","持久绑定",1110,475,140,35,22,C.teal);
  text(s1,"profile-claim","首期机制\nprompt replacement\n全局 L2 裁剪 Δ₂ ≤ 2C",70,520,235,125,22,C.muted);
  text(s1,"scope","首期：固定形状、单次发布\n扩展：固定 T 的逐步组合会计",70,710,640,76,25,C.ink);
  text(s1,"failure","故障：预算不足或账本不可写则拒绝\n重试：复用载荷，未知出站保守计费",820,710,710,76,25,C.ink);
  text(s1,"status","拟实现架构。现有裁剪与拆分基线可复用，Gaussian、持久账本和发布事务待实现",70,823,1320,42,21,C.muted);
  s1.speakerNotes.text="设计方案，尚未实现DP保证。第一阶段固定公开形状、一次发布、prompt replacement邻接，完整向量全局L2裁剪为C时Δ2≤2C。解析Gaussian校准和跨会话组合会计必须单独验证，固定T扩展需分析每一步条件机制及完整transcript。发布前原子预留预算，持久化唯一随机载荷后才发送；未知是否出站保守计费，重试不重采样。替换profile或回滚模型不能重置预算。现状核查：apps/agentOS/src/components/safe/application/privacy.py、contracts/privacy.py、infrastructure/privacy/accountant.py，当前guarantee=none且发布不可用。参考：Dwork & Roth https://www.cis.upenn.edu/~aaroth/Papers/privacybook.pdf；Analytic Gaussian https://arxiv.org/abs/1805.06530；RDP https://arxiv.org/abs/1702.07476。完整设计：papers/architecture/ARCHITECTURE_DESIGN.md第2节。";
  const s2=page("前导模型：意图理解与本地前段","语义入口确定任务，模型前段控制计算与外发位置",2);
  text(s2,"intent-lane","意图理解入口",70,205,1460,36,25,C.teal,true);
  const t=[
    node(s2,"input","请求与上下文\n授权来源",70,265,240,125),
    node(s2,"intent","意图解析\n本地模型优先",370,265,240,125,C.pale),
    node(s2,"profile","画像校验\n按需澄清",670,265,240,125),
    node(s2,"planner","Planner\n能力与计划",970,265,240,125),
    node(s2,"runtime","Runtime\n策略与绑定",1270,265,260,125,C.pale)
  ];for(let i=0;i<t.length-1;i++)link(s2,t[i],t[i+1]);
  text(s2,"split-lane","本地前导网络与拆分推理",70,450,1180,40,25,C.teal,true);
  const low=[
    node(s2,"output","结果验收\n交付与轨迹",70,520,240,125),
    node(s2,"local-result","本地接收\n回执与 token",370,520,240,125),
    node(s2,"suffix","云端后段\nSuffix + KV",670,520,240,125),
    node(s2,"dp-gate","隐私发布门\n逐次计费",970,520,240,125,C.pale),
    node(s2,"prefix","本地前 K 层\nTokenizer + KV",1270,520,260,125,C.pale)
  ];for(let i=4;i>0;i--)link(s2,low[i],low[i-1],"left","right");
  link(s2,t[4],low[4],"bottom","top");
  segment(s2,"decode-left-leg",490,645,0,55,false,false);
  segment(s2,"decode-horizontal",490,700,910,0,false,false);
  segment(s2,"decode-right-leg",1400,645,0,55,true,false);
  text(s2,"decode-caption","下一 token 的新激活再次经过发布门",670,712,650,42,23,C.teal);
  text(s2,"manifest","会话固定 manifest、模型版本与 K；故障不改发原文",70,765,1460,42,25,C.ink);
  text(s2,"status","现有：结构化画像、真实拆分和认证链路。待补：字段来源 / 选择性澄清 / DP 发布接线",70,823,1330,42,21,C.muted);
  s2.speakerNotes.text="此页同时呈现两种前导模型。上方是语义入口，下方是同一LLM连续前K层拆分。建议意图入口本地绑定，现有IntentParser可接可选LLM，并不证明已本地部署。字段provenance、必要澄清及修订是待补模块。Runtime负责真实身份、资源和策略，意图解析如果需远程调用也必须经过外发策略。拆分基线Tokenizer/embedding/前K层和前段KV在本机；Suffix/后段KV及基线LM head在云端，返回token后本地继续decode，每次新激活需计费。本页下方是split分支，Runtime另可选择批准的全本地完整模型；DP不可用不能静默发送raw prompt。固定manifestDigest/session/request/step，KV重启失效但隐私账本保留。现状核查：components/planner/intent_analyzer.py、components/safe/README.md。参考：CLAM https://arxiv.org/abs/2212.07769；RouteLLM https://arxiv.org/abs/2406.18665；ActInv相关 https://arxiv.org/abs/2605.23158。完整设计：papers/architecture/ARCHITECTURE_DESIGN.md第3节。";
  const s3=page("自进化：图与 Skills 的证据闭环","两类候选共享评测与版本发布，未来 Run 固定采用已批准版本",3);
  const ev=node(s3,"evidence","轨迹与验收\nEvidence Store",70,300,230,145);
  const dg=node(s3,"diagnosis","失败 / 成功聚合\n诊断与证据归因",350,300,230,145);
  const gp=node(s3,"graph-patch","图结构候选\nGraphPatch",650,230,260,115,C.pale);
  const sp=node(s3,"skill-patch","技能版本候选\nADD / PATCH",650,415,260,115,C.pale);
  const it=node(s3,"iteration","统一迭代引擎\n静态校验 / 回放\n独立确认",1010,290,250,165);
  const pb=node(s3,"publish","版本发布\n授权 + CAS",1340,300,190,145);
  link(s3,ev,dg);link(s3,dg,gp);link(s3,dg,sp);link(s3,gp,it);link(s3,sp,it);link(s3,it,pb);
  text(s3,"graph-op","先插入已注册验证器",650,350,285,45,22,C.muted);
  text(s3,"skill-op","保留来源、反例和适用范围",650,535,330,45,22,C.muted);
  const fr=node(s3,"future-run","未来 Run\n固定图 / 技能 / 模型版本",1130,615,400,110);
  link(s3,pb,fr,"bottom","top");
  segment(s3,"feedback-horizontal",185,670,945,0,false,false);
  segment(s3,"feedback-vertical",185,445,0,225,true,false);
  text(s3,"feedback-label","新任务证据回流",370,675,530,40,23,C.teal);
  text(s3,"protected-ledger","演化回滚生成新版本，隐私消费账本持续累计",70,765,1460,42,25,C.ink);
  text(s3,"status","现有：轨迹、受限图候选与 policy 事务。待补：真实回放 / 正式图发布 / Skills 演化算法",70,823,1330,42,21,C.muted);
  s3.speakerNotes.text="拟实现架构。证据输入包含独立Run、taskFamily、时间、血缘、验收、来源以及真实skillUsage事件。现有Run投影尚未填source_skill_ids，不能声称已有完整归因。图分支从registered_validator_insertion起步；Skills先ADD/PATCH，GraphProposal和SkillProposal保持typed contract，不混成同一种图。统一迭代引擎分开发集、选择集和独立确认集；候选冻结，质量、成本、历史能力非劣按预先策略验收，ID隔离还要补任务族/时间/内容血缘。发布由正式目标权威执行鉴权、CAS、事务和幂等回执；运行时修复仍归Runtime。现有图编排有生产依赖缺口，SkillEvolutionService四方法未实现。回滚只产生新版本，DP账本不可回滚或清零，演化不能自行批准新隐私机制。参考：AFlow https://arxiv.org/abs/2410.10762；GEPA https://arxiv.org/abs/2507.19457；PASE https://arxiv.org/abs/2611.14019；Evidence-Governed Adoption https://arxiv.org/abs/2611.16378。完整设计：papers/architecture/ARCHITECTURE_DESIGN.md第4节及papers/EVOLUTION_IMPLEMENTATION_PLAN.md。";
  nodeRepl.write({slides:presentation.slides.items.map(s=>({id:s.id,size:s.size})),font:"Microsoft YaHei"});
}, {artifactRef:"artifact_gaRLsnVQIuY_BluhayRhrBflr9og3uki",artifactType:"presentation"});
