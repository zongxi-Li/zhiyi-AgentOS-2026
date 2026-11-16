# AgentOS 部件化统一设计

本文件固定 AgentOS 的目录与职责边界，更新于 2026-11-16。`components/` 固定为 **13 个部件：9 个核心部件、2 个 basic 基础部件、2 个 great 增强部件**。core/basic/great 是职责分组，不额外增加目录层级，也不表示执行顺序或完成程度。

下方列出已落地的主要目录；部件内部按实际职责继续细分。本轮迁移同步了源码导入、应用装配、启动脚本和根目录 `TEST/tests/` 的测试入口。目录归位不表示尚未接入的调度、隐私或产品能力已完成，具体边界见文末。

模型兼容端点的 registry 复用、生命周期、SSE 与外部框架边界见
[模型运行时装配](docs/模型运行时接入方案.md)。Gitee 分叉提交的迁移判定见
[Gitee 模型运行时迁移检查](docs/Gitee模型运行时迁移评估.md)。

## 目录结构

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
│     ├─ run_locks.py                    共享运行锁的唯一实现
│     └─ run_execution_fence.py          并发运行围栏等技术辅助
│
├─ docs/                                 设计、实施说明和迁移记录
└─ data/                                 本地运行/实验数据与制品
```

`runtime/` 根仅保留轻量公开入口和 `workflow_runtime.py` 门面；`adapters/` 根只导出公开适配器。各部件按实际复杂度设立 `models.py`、`service.py`、`algorithms.py`、`store.py`，或细分为 `application/`、`domain/`、`ports/`、`infrastructure/`。`safe` 的内部边界见其[模块设计](src/components/safe/README.md)。

## 分层与依赖规则

| 层 | 负责什么 | 边界 |
| --- | --- | --- |
| contracts | 公开 DTO、事件、能力协议和结构校验 | 不访问数据库、网络、模型或 runtime；部件私有类型留在部件内部 |
| domain | 共享实体、身份关系、不变量、领域仓储接口 | 仅依赖必要的基础合同；不依赖部件、编排或具体 IO |
| components | 业务规则、部件内用例与对外门面 | 通过公开合同/门面协作；不导入其他部件的内部实现或顶层 runtime |
| runtime | 部件装配、跨部件用例、查询投影和事件协调 | 知道“先调谁、如何提交”，不重新实现规划、调度、审计、恢复算法 |
| adapters / storage | 外部系统适配、协议转换与数据库实现 | 实现接口；不裁定业务策略，不反向调用 runtime 门面 |
| tools / support | 导出、兼容与技术服务基础 | 不成为第二套规划器、调度器或共享业务合同层 |

目标依赖方向如下。箭头表示源码依赖，业务执行顺序见下一节。

```text
外部应用 / API → runtime 公开门面
runtime/composition → 部件公开门面 + adapters + storage + support
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
- **scheduler / resource**：scheduler 已统一依赖满足判定和就绪节点选择，由 executor 委派调用；resource 维护资源事实，通过 `resource/scheduler/` 提供资源评分、绑定与容量租约。当前就绪集与资源准入分阶段执行，尚无统一求解容量、权限、预算约束的最大子图优化器。
- **mission / environment / projections**：mission 管理工程、会话关联与顶层任务；environment 管理真实文件工作区、内容引用与沙盒；runtime 的 workspace 投影只聚合展示信息，不成为第二个工程或文件工作区管理器。
- **memory / attachments / storage**：memory 决定哪些信息成为记忆、如何检索与更新；attachments 提供原始材料、文本/结构抽取和存储数据服务，抽取结果由 memory 决定是否写入记忆；storage 实现共享实体仓储。材料读写不等于记忆读写，不绕过 memory 的权限与语义规则。
- **executor / environment**：executor 推进图节点并验证执行收据；environment 的 Hands 执行受限文件/Shell 操作，compact 压缩上下文。二者各自保留独立的 TypeScript 构建、依赖与测试，通过明确协议接入 Python，不另建任务调度器。
- **communicator / safe / auditor**：communicator 管消息内容契约、压缩与血缘；safe 管拆分模型执行、激活出站和隐私机制；auditor 管治理与授权判定。压缩、裁剪、摘要或拆分推理都不自动构成差分隐私，DP 需要明确机制、邻接关系与预算会计。
- **recovery / planner / evolution**：recovery 选择恢复动作并请求局部重规划，planner 产出修订提案；evolution 基于经验提出 skills/图候选版本。新版本须经评估、审计和显式激活，不直接改写运行中的图。

## runtime 职责归位

`ExecutionRuntime` 保留稳定类名与公开入口，委派 `orchestration/workflow.py` 的应用用例。以下记录迁移后的职责归属；跨部件版本校验和事务协调继续保留在编排层。

| 模块或职责 | 归属 | runtime 保留部分 |
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
- **原 service/agents**：Agent 协议、注册与调用适配位于 `adapters/agent/`；实例池、供给与资格管理位于 `components/resource/agents/`。旧 `service/` 不再保留第二套 Python 实现。
- **environment**：按用户确定的目录容纳 content/hands/compact；语言与进程边界保持独立，不能把 TypeScript 源码当成 Python 包直接导入。配置、进程启动路径和测试收集规则需随迁移校正。
- **safe**：整体归入 `components/safe/`，复用其合同、领域、用例和基础设施分层；通用模型分区校验与拆分推理通过单一适配边界衔接。隐私发布与预算未接通前，继续明确拒绝相关执行。

## 迁移结果与能力边界

以下状态按 2026-11-16 源码核对。实现与合同各保留一个权威定义；旧入口只在仍有调用的兼容范围内转发。

| 范围 | 当前实现与边界 |
| --- | --- |
| mission / domain | 工程语义、初始规划输入和身份生命周期归 mission；共享生命周期规则及纯图规则归 domain。 |
| scheduler | 唯一依赖就绪选择实现，覆盖条件路由、已完成/跳过节点与控制分支；resource 保留唯一资源绑定和租约权威。 |
| environment | content/hands/compact 各保留自身项目边界；Python 通过协议调用，运维与发布脚本使用新路径。 |
| safe / model_partition | safe 整体位于 `components/safe/`；分区合同仍在 `contracts/model_partition.py`，校验服务位于 `safe/integration/model_partition.py`。该服务只验证层区间和张量边界，执行仍抛出 `MODEL_PARTITION_UNAVAILABLE`。safe 的显式拆分推理用例有独立的装配边界，详见[模块状态](src/components/safe/README.md)。 |
| resource/catalog | 原 marketplace 的安装目录与安装任务已归并，不增加顶层部件。 |
| runtime | composition/orchestration/projections/events/compatibility 五包已建立；纯审核规则归 auditor、初始编译及语义补丁归 planner、配额规则归 resource。写入身份状态的投影协调留在 orchestration。 |
| planner / executor 编译边界 | `planner/package_compiler.py` 唯一负责蓝图到不可变执行包；`executor/compiler.py` 继承编译入口，仅提供执行图适配。编译策略指纹同时覆盖两份源码，旧公开类入口保持可用。 |
| adapters / Agent 服务 | model/agent/tool/retrieval/transport 五包已建立；Agent 注册与适配归 adapters，实例供给归 resource。 |
| contracts / support/acg | ACG 合同归 `contracts/acg/`，校验归 planner，纯图规则归 domain；`support/acg/` 只转发。完整字段摘要复用 `contracts/stable_digest.py`，省略默认值的 `stable_checksum` 保留原有不同语义。 |
| storage / support/stores | 共享领域仓储与历史 WorkflowStore 的数据库 schema 继续隔离。 |

迁移前快照为 `faf7ba8a`，目录与源码迁移检查点为 `1c63269b`。实施计划见[迁移计划](../../docs/superpowers/plans/2026-11-15-agentos-architecture-convergence.md)；各批次结果和未通过项见[迁移与验证记录](../../docs/audits/2026-11-16-agentos-architecture-convergence.md)。

在仓库根目录运行 Python 回归；应用集成测试还需安装 `apps/agent/requirements.txt` 中的依赖：

```powershell
python -m pytest --rootdir=. -c apps/agentOS/pytest.ini TEST/tests/architecture TEST/tests/components/scheduler -q
python -m pytest --rootdir=. -c apps/agentOS/pytest.ini TEST/tests/domain TEST/tests/runtime TEST/tests/storage -q
python -m pytest --rootdir=. -c apps/agentOS/pytest.ini TEST/tests/safe TEST/tests/components/test_model_partition.py -q
```

Hands 与 compact 的命令分别在 `src/components/environment/hands/` 和 `src/components/environment/compact/` 执行，Node 版本要求以各自 `package.json` 为准。架构守卫检查固定部件集合、runtime/adapters 分组、领域层依赖方向以及旧根目录是否残留第二套实现；不会用跳过业务断言来达成目录验收。

从仓库根启动时必须像上例显式传入 `TEST/tests/` 或其子目录；从 `apps/agentOS/` 启动时可用 `python -m pytest` 按配置收集。测试使用 importlib 导入方式和原生 `TEST.tests` 包，避免同名测试模块互相覆盖，并保证 Windows 多进程能够重新导入。仓库根命令使用 `--rootdir=.`，使测试节点路径与冻结门禁保持一致。

[架构冗余与错位分析](docs/架构冗余与错位分析.md)保留为 2026-11-09 的历史审计；其中旧部件数、文件数、TypeScript 归属和 `storage/v2` 路径不作为本版目标结构的依据。
