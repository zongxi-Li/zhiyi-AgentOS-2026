# AgentOS 部件化统一设计（目标结构）

```text
AgentOS
│
├─ 设计规则
│  ├─ 一个业务部件 = 一个文件夹
│  ├─ 部件内部自包含：contracts / models / service / algorithms / store
│  ├─ 跨部件仅依赖 src/contracts/；禁止读取其他部件内部状态
│  ├─ adapters/ 只承载 SQLite、LLM、向量库、远程 Agent 等外部实现
│  └─ 运行时只负责编排部件，不承载业务算法
│
├─ config 运行的配置文件
│
│
├─ src/contracts/                         跨部件唯一共享合同
│  ├─ task.py                             Task、任务约束、生命周期事件
│  ├─ workflow.py                         ACG Blueprint、RuntimeGraph、节点与边
│  ├─ execution.py                        ExecutionPackage、Outcome、执行状态
│  ├─ communication.py                    Message、ContextPack、字段与版本契约
│  ├─ memory.py                           MemoryRecord、Query、Policy、WriteBatch
│  ├─ resource.py                         ResourceProfile、Snapshot、Lease、Decision
│  ├─ governance.py                       Trace、Checkpoint、AuditRequest、PolicyDecision
│  └─ recovery.py                         FailureEvent、RecoveryPlan、GraphPatch
│
├─ src/task_manager/                      任务管理器
│  ├─ models.py                           Task、配额、优先级、任务状态
│  ├─ state_machine.py                    任务/运行合法状态迁移
│  ├─ service.py                          创建、绑定、取消、恢复、进度查询
│  ├─ scheduler.py                        多用户/多任务排队、优先级与配额调度
│  ├─ algorithms.py                       复杂度评分、优先级排序、并发配额分配
│  └─ store.py                            TaskStore Interface 及 SQLite / Memory Adapter
│  
│
├─ src/planner/                           规划器：Task → 静态 ACG Blueprint
│  ├─ models.py                           Intent、TaskProfile、Capability、PlanningVariant
│  ├─ intent_analyzer.py                  LLM / 启发式意图理解
│  ├─ task_structurer.py                  目标、约束、风险、预算、子任务结构化
│  ├─ cognitive_router.py                 能力 → Agent/角色候选路由
│  ├─ template_matcher.py                 模板检索、相似度评分、静态优选
│  ├─ acg_builder.py                      Step/Agent/Memory/Evidence/Control 图构建
│  ├─ algorithms.py                       模板评分、能力依赖展开、熵预算、多样性选择
│  └─ service.py                          输出可审计的 ACG Blueprint
│  
│
├─ src/resource/                          资源器：资源画像与健康状态
│  ├─ models.py                           ResourceProfile、ResourceSnapshot、ResourceMetric
│  ├─ registry.py                         注册 Agent/模型/工具/知识源，维护版本与权限
│  ├─ health.py                           心跳、健康检查、负载/时延/可靠性更新
│  ├─ algorithms.py                       指数移动平均、健康评分、资源可用性判定
│  ├─ store.py                            ResourceStore Interface 及持久化 Adapter
│  └─ service.py                          对调度器提供资源候选与实时快照
│  
│
├─ src/scheduler/                         调度器：Blueprint → Runtime Execution Plan
│  ├─ models.py                           Binding、SchedulingRequest、Decision、ResourceLease
│  ├─ binder.py                           将抽象能力绑定到可执行资源候选
│  ├─ scorer.py                           候选标准化评分与稳定并列决策
│  ├─ leases.py                           原子预留、超时回收、并发槽位控制
│  ├─ package_builder.py                  组装无状态 ExecutionPackage
│  ├─ algorithms.py                       多目标评分、权重归一化、退避与候选切换
│  └─ service.py                          选优、租约、反馈更新与调度审计
│  
│
├─ src/executor/                          执行器：RuntimeGraph 的确定性执行
│  ├─ graph.py                            RuntimeGraph、就绪集、图版本、条件分支
│  ├─ dispatcher.py                       并发批次、Agent 调用、超时与取消
│  ├─ barrier.py                          原子提交、迟到结果拒绝、状态投影
│  ├─ service.py                          执行、续跑、人审后继续
│  ├─ algorithms.py                       拓扑排序、就绪节点选择、并发限流
│  └─ fault_injection.py                  可控故障注入
│ 
│
├─ src/communicator/                      通信器：受控低熵信息流
│  ├─ models.py                           Message、MessageEnvelope、ContextPack、ProvenanceEvent
│  ├─ contracts.py                        Schema 版本校验、适配和字段投递规则
│  ├─ assembler.py                        从上游、记忆、证据装配最小充分上下文
│  ├─ compressor.py                       字段裁剪、去重、Token 预算压缩
│  ├─ provenance.py                       生产/消费/路由血缘与完整性校验
│  ├─ algorithms.py                       低熵选择、Token 估算、消息重试/幂等
│  └─ service.py                          投递、确认、异常上报
│  
│
├─ src/memory/                            记忆器：唯一记忆读写入口
│  ├─ models.py                           六类 MemoryRecord、Query、Policy、ContextRequest、WriteBatch
│  ├─ store.py                            MemoryStore Interface；Memory / SQLite / Vector Adapter
│  ├─ admission.py                        权限、证据、风险、版本、幂等准入
│  ├─ retrieval.py                        过滤、关键词/向量/关系召回、去重、冲突保留、重排
│  ├─ compression.py                      按 Token 预算选择与类型化压缩
│  ├─ lifecycle.py                        工作→情节→语义/程序记忆的巩固与过期
│  ├─ algorithms.py                       混合召回、权威/时效/效用评分、背包式预算选择
│  └─ service.py                          生成 ContextPack、原子写入、快照恢复
│ 
│
├─ src/auditor/                           审计器：继续传播的治理判定
│  ├─ models.py                           AuditRequest、Finding、AuditReport、PolicyDecision
│  ├─ structural.py                       图/状态/契约/版本校验
│  ├─ evidence.py                         结论—证据—来源—过程一致性校验
│  ├─ risk.py                             风险事实、规则匹配、冲突消解
│  ├─ quality.py                          输出完整性、一致性、质量阈值检查
│  ├─ policy.py                           规则版本、自动动作与人工审核分流
│  ├─ algorithms.py                       综合评分、规则优先级、决策合并
│  └─ service.py                          输出 PolicyDecision 与审计事件
│  
│
├─ src/recovery/                          恢复器：受控自愈与局部重规划
│  ├─ models.py                           FailureEvent、CheckpointRef、RecoveryPlan、GraphPatch
│  ├─ classifier.py                       统一故障分类与可恢复性判定
│  ├─ checkpoint.py                       检查点创建、校验、选择与上下文重建
│  ├─ planner.py                          重试、换资源、补证、审核、局部图补丁决策
│  ├─ validator.py                        补丁身份、预算、能力、连通性校验
│  ├─ algorithms.py                       最近安全检查点选择、恢复动作优先级
│  └─ service.py                          应用恢复计划并重新进入审计闭环
│  
│
├─ src/runtime/                           薄编排器：只连接部件 Interface
│  ├─ bootstrap.py                        创建部件、注册原生能力和 Pack
│  ├─ workflow_runtime.py                 Task → Planner → Scheduler → Executor 编排
│  ├─ dependencies.py                     依赖注入与生命周期
│  └─ compatibility.py                    旧 core/* API 的过渡 Facade
│  
│
├─ src/adapters/                          外部 Adapter
│  ├─ model/                              DeepSeek、Qwen、其他模型实现
│  ├─ tool/                               工具运行时实现
│  ├─ storage/                            SQLite、Memory、Vector Store 实现
│  ├─ retrieval/                          Chroma、代码/教育/法律索引实现
│  └─ remote_agent/                       HTTP/gRPC Agent Adapter
│
│
├─ tools/                                 相关工具
│  ├─ exporter.py                         ACGBlueprint / RuntimeGraph → 稳定 JSON
│  ├─ serializer.py                       节点、边、状态、绑定、证据和图版本的序列化
│  ├─ mermaid.py                          JSON → Mermaid flowchart 文本
│  ├─ graphviz.py                         JSON → Graphviz DOT 文本
│  ├─ labels.py                           节点类型、状态、边类型的显示标签与样式映射
│  └─ service.py                          export_json / render_mermaid / render_dot 统一入口
│ 
│ 
└─ tests/
   ├─ task_manager/ planner/ resource/ scheduler/ executor/
   ├─ communicator/ memory/ auditor/ recovery/ runtime/
   └─ contract/                           合同兼容、跨部件集成、故障与并发场景


核心算法
├─ 任务复杂度：目标长度、文件数、模态、风险、Step 估计、跨域与可选路径加权
├─ 规划：模板相似度阈值 → 能力依赖展开 → 熵预算约束 → ACG 构建
├─ ACG 导出：Canonical JSON 序列化 → 节点/边类型映射 → Mermaid 或 DOT 渲染文本
├─ 资源调度：硬过滤 → 技能/可靠性/健康/空闲/时延/成本/网络距离加权评分 → 租约
├─ 执行：拓扑就绪集 → 资源并发限制 → 批次屏障原子提交 → 条件图补丁
├─ 低熵通信：字段契约过滤 → 去重 → Token 预算压缩 → 消息血缘记录
├─ 记忆：权限过滤 → 混合召回 → 冲突保留 → 评分重排 → 得分/Token 预算选择
├─ 审计：结构、证据、风险、质量并行检查 → 规则优先级合并 → PolicyDecision
└─ 恢复：故障分类 → 最近安全检查点 → 重试/换资源/补证/补丁/审核 → 重新审计
```
