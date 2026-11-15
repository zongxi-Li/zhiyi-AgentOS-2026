# AgentOS 部件化统一设计

本文件固定 AgentOS 的目标目录与职责边界，更新于 2026-11-15。`components/` 固定为 **13 个部件：9 个核心部件、2 个 basic 基础部件、2 个 great 增强部件**。core/basic/great 是职责分组，不额外增加目录层级，也不表示执行顺序或完成程度。

下方目录树是收敛目标，不是当前文件系统快照；尚未完成的移动、拆分和接入见文末对应表。本次仅更新目录设计文档，不代表代码迁移或能力验收已经完成。

模型兼容端点的 registry 复用、生命周期、SSE 与外部框架边界见
[模型运行时装配](docs/模型运行时接入方案.md)。Gitee 分叉提交的迁移判定见
[Gitee 模型运行时迁移检查](docs/Gitee模型运行时迁移评估.md)。

## 目标目录

```text
agentOS/
├─ src/
│  ├─ contracts/                         跨部件、跨进程的公开数据合同与能力协议
│  │                                      ACG、身份、资源、执行、通信、治理、事件等
│  │
│  ├─ domain/                            共享领域内核：实体、值对象、不变量、仓储接口
│  │  ├─ models.py                       Mission / SemanticTask / Run / Attempt / Step
│  │  ├─ identity_graph/                 身份关系、绑定与解析规则
│  │  ├─ lifecycle_projection.py         生命周期到领域状态的纯映射
│  │  └─ repository/                     领域仓储接口与领域存取错误；无数据库实现
│  │
│  ├─ components/                        业务部件层（固定 13 个）
│  │  ├─ mission/                        [core] 工程管理器：会话工程、顶层任务与生命周期
│  │  ├─ planner/                        [core] 规划器：任务分解、ACG 规划、编译与修订提案
│  │  ├─ resource/                       [core] 资源器：画像、健康、快照、资源绑定与容量租约
│  │  ├─ scheduler/                      [core] 调度器：中枢，划分当前最大可执行子图
│  │  ├─ executor/                       [core] 执行器：RuntimeGraph 确定性推进与结果提交
│  │  ├─ communicator/                   [core] 通信器：受控低熵信息流、消息契约与血缘
│  │  ├─ memory/                         [core] 记忆器：唯一记忆读写入口、抽取策略与召回
│  │  ├─ auditor/                        [core] 审计器：治理判定、证据检查与执行许可规则
│  │  ├─ recovery/                       [core] 恢复器：受控自愈、检查点与局部重规划请求
│  │  ├─ attachments/                    [basic] 存储器：材料抽取、记忆抽取的数据服务与存储
│  │  ├─ environment/                    [basic] 环境器：内容工作区、沙盒、执行及上下文压缩工具
│  │  │  ├─ content/                            内容工作集、内容清单与内容引用
│  │  │  ├─ hands/                              独立工具执行引擎（TypeScript 项目）
│  │  │  └─ compact/                            独立上下文压缩引擎（TypeScript 项目）
│  │  ├─ evolution/                      [great] 进化器：skills 进化、图自进化与候选版本评估
│  │  └─ safe/                           [great] 安全部件：拆分推理、激活边界与差分隐私机制
│  │                           
│  │
│  ├─ runtime/                           应用编排层：装配部件、驱动用例、组织跨部件协作
│  │  ├─ __init__.py                     稳定公开入口；轻量导出
│  │  ├─ workflow_runtime.py             运行时门面；委派用例，不内置部件算法
│  │  ├─ composition/                    依赖装配、配置解析、注册、进程生命周期
│  │  ├─ orchestration/                  启动/规划/执行/审核/恢复的跨部件用例与提交协调
│  │  ├─ projections/                    工程视图、执行视图、查询聚合与只读展示投影
│  │  ├─ events/                         运行进度事件分发、订阅与生命周期通知
│  │  └─ compatibility/                  入口与导入层的转发；不新增业务规则
│  │
│  ├─ adapters/                          外部能力接入层；实现公开协议，由 composition 注入
│  │  ├─ model/                          模型供应商与模型运行时适配
│  │  ├─ agent/                          外部 Agent、架构注册与调用适配
│  │  ├─ tool/                           工具调用、Hands/compact 进程或 HTTP 协议适配
│  │  ├─ retrieval/                      检索服务接入；记忆选择策略仍属于 memory
│  │  └─ transport/                      通用 HTTP/远端 Runtime 传输；部件专用实现留在部件内
│  │
│  ├─ storage/                           共享领域实体的数据库实现，不承载业务存储策略
│  │  ├─ sqlite.py                       连接与事务基础设施
│  │  ├─ schema.py                       Identity / New ACG 数据表与版本管理
│  │  └─ repositories.py                 实现 domain/repository 中的接口
│  │
│  ├─ tools/                             ACG 只读导出、规范化序列化、Mermaid/DOT 绘图
│  │                                      工具执行环境归 environment，图编译算法归 planner
│  │
│  └─ support/                           历史兼容与通用技术配套；不新增业务权威
│     ├─ acg/                            迁移期兼容入口；合同归 contracts，规划规则归 planner
│     ├─ packs/                          Pack Manifest 发现与注册基础设施
│     ├─ skills/                         BaseSkill、NoOpSkill 与注册表基础设施
│     ├─ stores/                         历史 WorkflowStore 实现；与 storage 的 schema 隔离
│     ├─ async_tasks.py                  异步任务技术辅助
│     └─ run_execution_fence.py          并发运行围栏等技术辅助
│
├─ docs/                                 设计、实施说明和迁移记录
└─ data/                                 本地运行/实验数据与制品
```

`runtime/` 和 `adapters/` 的分组目录是目标结构，当前多数文件仍平铺。各部件只按实际复杂度设立 `models.py`、`service.py`、`algorithms.py`、`store.py`，或细分为 `application/`、`domain/`、`ports/`、`infrastructure/`；不为目录对称创建空层。`safe` 的细分结构继续遵循其[模块设计](src/safe/README.md)，迁移时整体保留内部边界。

## 分层与依赖规则

| 层 | 负责什么 | 边界 |
| --- | --- | --- |
| contracts | 公开 DTO、事件、能力协议和结构校验 | 不访问数据库、网络、模型或 runtime；部件私有类型留在部件内部 |
| domain | 共享实体、身份关系、不变量、领域仓储接口 | 仅依赖必要的基础合同；不依赖部件、编排或具体 IO |
| components | 业务规则、部件内用例与对外门面 | 通过公开合同/门面协作；不导入其他部件的内部实现或顶层 runtime |
| runtime | 部件装配、跨部件用例、查询投影和事件协调 | 知道“先调谁、如何提交”，不重新实现规划、调度、审计、恢复算法 |
| adapters / storage | 外部系统适配、协议转换与数据库实现 | 实现接口；不裁定业务策略，不反向调用 runtime 门面 |
| tools / support / service | 导出、兼容与技术服务基础 | 不成为第二套规划器、调度器或共享业务合同层 |

目标依赖方向如下。箭头表示源码依赖，业务执行顺序见下一节。

```text
外部应用 / API → runtime 公开门面
runtime/composition → 部件公开门面 + adapters + storage + service
runtime/orchestration → 部件公开门面 + contracts + 必要的 domain 接口
runtime/projections → 公开查询接口 + contracts / domain
components → contracts + 共享 domain；外部能力经注入的 ports 使用
adapters → contracts / 部件公开 ports；storage → domain/repository
domain → 必要的基础 contracts；contracts 不反向依赖以上各层
tools → 公开 ACG 合同 / planner 的只读导出门面
```

部件内部的基础设施由组合根显式装配。部件间若必须直接协作，只使用公开门面或注入接口，并保持依赖无环；不得通过导入其他部件的 store、算法或私有模型实现复用。当前遗留的内部导入属于迁移项，不能据此新增依赖。

顶层 `contracts/` 只收跨部件共享或跨进程传输的合同。部件内部可保留本地合同与 ports；同一合同只有一个权威定义，本地入口可以重导出。共享实体归 `domain`，工程业务归 `mission`，避免再增设 identity/workspace 等顶层业务部件。

## 部件协作与职责边界

主链路为：`mission` 建立工程与顶层任务 → `planner` 生成 ACG → `auditor` 检查候选图与授权条件 → `scheduler` 结合 `resource` 快照形成可执行批次 → `executor` 推进节点 → 结果提交并形成审计证据。`runtime` 组织这条链路；遇到人工审核、等待资源或失败时，分别协调审核、等待和 `recovery` 用例。

- **planner / scheduler / executor**：planner 决定“任务如何分解、图如何连接”；scheduler 决定“当前哪些节点可以执行”；executor 决定“按已批准图如何推进并提交结果”。“当前最大可执行子图”以依赖满足、资源容量、权限、预算和并发限制为约束，目标是扩大当前可行执行集合，不宣称已实现全局最优求解。
- **scheduler / resource**：resource 维护资源事实，提供唯一的绑定与容量租约服务；scheduler 用这些结果选择执行批次，不复制资源评分、绑定或租约权威。当前 `resource/scheduler/` 中的绑定实现需先划清资源分配与图调度职责，再决定内部文件归属。
- **mission / environment / projections**：mission 管理工程、会话关联与顶层任务；environment 管理真实文件工作区、内容引用与沙盒；runtime 的 workspace 投影只聚合展示信息，不成为第二个工程或文件工作区管理器。
- **memory / attachments / storage**：memory 决定哪些信息成为记忆、如何检索与更新；attachments 提供原始材料、文本/结构抽取和存储数据服务，抽取结果由 memory 决定是否写入记忆；storage 实现共享实体仓储。材料读写不等于记忆读写，不绕过 memory 的权限与语义规则。
- **executor / environment**：executor 推进图节点并验证执行收据；environment 的 Hands 执行受限文件/Shell 操作，compact 压缩上下文。二者各自保留独立的 TypeScript 构建、依赖与测试，通过明确协议接入 Python，不另建任务调度器。
- **communicator / safe / auditor**：communicator 管消息内容契约、压缩与血缘；safe 管拆分模型执行、激活出站和隐私机制；auditor 管治理与授权判定。压缩、裁剪、摘要或拆分推理都不自动构成差分隐私，DP 需要明确机制、邻接关系与预算会计。
- **recovery / planner / evolution**：recovery 选择恢复动作并请求局部重规划，planner 产出修订提案；evolution 基于经验提出 skills/图候选版本。新版本须经评估、审计和显式激活，不直接改写运行中的图。

## runtime 收敛

不能仅把现有文件搬进子目录。应先按职责拆分，再保留必要的编排部分；以下对应的是职责去向，不是整文件机械迁移清单。

| 当前模块或职责 | 目标去向 | runtime 保留部分 |
| --- | --- | --- |
| `bootstrap`、`dependencies`、`app_setup`、装配用的 `ports/context` | `runtime/composition/` | 依赖创建、配置、注入、关闭；共享能力协议上提公开接口 |
| `workflow_runtime` 与各类 Coordinator | 薄门面 + `runtime/orchestration/` | 跨部件调用顺序、取消/等待、幂等与提交协调 |
| `planning_*`、`initial_graph_compilation`、`planner_*` | 规划算法、图编译和提案校验归 planner；材料准备调用 attachments/environment | 发起规划、收集公开输入、等待确认并提交结果 |
| `graph_materialization`、`graph_activation`、`graph_handoff`、`graph_revision` | 编译归 planner；就绪子图/交接归 scheduler；执行状态归 executor；工程版本归 mission；共享身份不变量归 domain | 跨部件版本一致性检查的协调与原子提交边界 |
| `execution_permit`、`human_review_policy`、`review` | 许可与审核判定规则归 auditor | 接收外部审核结果、调用审计门面并继续/终止用例 |
| `acg_execution`、`binding`、`state_persistence` | 图推进归 executor；批次选择归 scheduler；资源绑定归 resource；持久化调用注入接口 | 用例入口与跨部件提交协调 |
| `runtime_recovery`、`permit_recovery` | 恢复策略归 recovery；许可规则归 auditor | 故障转交、调用恢复门面并重新进入主链路 |
| `semantic_patch`、`semantic_revision`、工程状态迁移 | 工程语义与状态机归 mission；图修订算法归 planner | 修订请求、审批、版本切换的跨部件协调 |
| `workspace`、`queries`、`query_models`、各类展示 projection | 只读聚合归 `runtime/projections/`；共享身份规则归 domain；领域状态写入归所属部件 | 稳定查询入口；投影重建只写派生读模型 |
| `live_events`、`runtime_display`、`model_quota` | 事件分发归 `runtime/events/`；展示归 projections；模型调用配额规则归 resource，调用端执行计量 | 订阅生命周期、投影输出与配额服务注入 |
| `compatibility`、旧导入与旧入口 | `runtime/compatibility/`；通用锁/围栏归技术辅助或所属基础设施 | 只转发，避免在兼容层产生新策略 |

runtime 可以协调跨部件事务、补偿和投影更新，但业务状态是否合法必须由所属部件或共享领域规则判断。`runtime/events` 是进程内进度通知，不替代 communicator 的业务消息可靠投递。

## 其他目录的收敛规则

- **adapters**：按模型、Agent、工具、检索和通用传输整理现有平铺文件。部件专用数据库、模型或隐私实现可留在该部件的 `infrastructure/`，顶层不复制一套实现。
- **storage**：当前路径已经是 `src/storage/`，文档不再使用旧 `storage/v2/`。它与 `support/stores/` 分别服务共享身份/New ACG 与历史 WorkflowStore，迁移不能直接合并 schema 或混用仓储。
- **tools**：只读导出与绘图，不承担 ACG 规划/编译，也不承担 Hands 工具执行。不能为了缩小 planner 而把领域算法转移到 tools。
- **support/acg**：数据合同迁入 contracts，规划算法与语义规则迁入 planner，注册基础设施按公开接口装配；原路径只在兼容期转发，禁止复制合同定义。
- **service/agents**：保留当前根级技术服务入口，提供 Agent 协议实现、注册和实例池；Agent 的资格选择属于 resource，执行时机属于 scheduler。
- **environment**：按用户确定的目录容纳 content/hands/compact；语言与进程边界保持独立，不能把 TypeScript 源码当成 Python 包直接导入。配置、进程启动路径和测试收集规则需随迁移校正。
- **safe**：整体归入 `components/safe/`，复用其合同、领域、用例和基础设施分层；通用模型分区校验与拆分推理通过单一适配边界衔接。隐私发布与预算未接通前，继续明确拒绝相关执行。

## 当前代码与目标的差异

以下状态按 2026-11-15 工作区核对，包含尚未提交的目录调整；路径出现不等于所有调用和测试已完成迁移。

| 当前状态 | 收敛目标 / 后续动作 |
| --- | --- |
| `mission/` 已存在，旧 `mission_manager/` 已移出；语义与修订类型已进入 mission | 固定使用 mission；核对公开导出、历史导入与调用方 |
| content、Hands、compact 已分别进入 `environment/content`、`environment/hands`、`environment/compact` | 固定 environment 归属；继续核对旧路径、启动脚本、构建与测试入口 |
| 尚无独立 `components/scheduler/`；资源分配位于 `resource/scheduler/`，图推进与就绪选择散见 runtime/executor；`mission/scheduler.py` 实为进度投影 | 建立统一的图调度门面；区分图就绪选择、资源绑定与工程进度投影，不按文件名机械迁移 |
| `safe` 仍位于 `src/safe/` | 后续整体迁入 `components/safe/`，同步公开导入、相对路径、架构守卫和测试；本文未移动代码 |
| `components/model_partition/` 仍独立存在，只做计划校验并拒绝执行 | 职责归入 safe，不作为第 14 个目标部件；迁移前保留旧入口及 `MODEL_PARTITION_UNAVAILABLE` 语义 |
| `components/marketplace/` 仍独立存在，负责本地安装目录与安装任务 | 归入 resource 的目录/安装用例；技术安装实现通过端口注入，不新增顶层部件或资源裁决权威 |
| `src/svolve/` 当前为空目录 | 不纳入目标层次；后续进化能力归 evolution，清理须与实际迁移一起处理 |
| runtime 仍平铺且混合编排、规则与投影；adapters 多数文件也平铺 | 按上表逐项拆分职责，再建立目标子包并迁移调用方 |
| `storage` 已平铺，`support/acg` 和历史 `support/stores` 仍存在 | 保持存储边界，逐步收敛 ACG 合同与兼容入口 |
| safe 已有进程内拆分生成用例；认证网络服务、DP 发布与持久预算尚未完成 | 以[模块状态与验证报告](src/safe/README.md)为能力依据，不以目录名称宣称安全或性能收益 |

迁移顺序：先稳定公开合同与部件门面，再归位 runtime 中的业务规则，随后移动目录并同步调用、配置与测试，最后缩减兼容入口。每步保持旧行为可验证，不能仅靠新增目录宣称已完成分层。

[架构冗余与错位分析](docs/架构冗余与错位分析.md)保留为 2026-11-09 的历史审计；其中旧部件数、文件数、TypeScript 归属和 `storage/v2` 路径不作为本版目标结构的依据。
