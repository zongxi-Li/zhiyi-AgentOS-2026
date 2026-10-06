# 知弈 AgentOS 前端设计书

作者： 李宗熹
初次修改： 2026.8.30
修改记录：
简要说明：对项目的ACG交互做了一轮样式更新，参考了vscode的设计模式，
我的想法就是项目之前是用户给输入系统给输出无法体现恢复闭环的这样一个功能，现在的改法就是用户提出这样一个输入然后进入这个编辑器。编辑器中会逐渐出现整体的ACG图，以及逐渐出现每一步的输入和输出。然后用户可以按照每一步的产入和产出进行修改，然后再重新运行，当前步骤的下面的一些步骤就会进行刷新,就可以体现出多轮对话的功能，同时这样也可以解决先导模型界面的问题，直接做成一个单独的标签页即可。

后期接入真正的代码能力之后可以认为是一个上层封装，就是纯文字页面但是是按照具体的功能和步骤分块的

> **文档定位**：本文件既是一份产品设计说明，也是一份前端架构与交互设计规范。前半部分面向任何第一次接触知弈 AgentOS 的读者，用尽量直白的方式解释“为什么这样设计”；后半部分保留工程实现、数据模型、Workbench 结构和扩展机制等技术细节，供产品、设计、前端、后端和答辩/评审人员共同使用。

---

# 0. 一页看懂这次重构

知弈 AgentOS 这一轮前端重构，最核心的变化不是“把页面做得像 VS Code”，也不是简单地更换颜色、布局或控件。

真正的变化是：**我们重新定义了用户在操作什么。**

过去，系统更像一个“提交任务后查看执行结果的页面”：

```text
新建 ACG 任务
→ 启动执行
→ 查看 ACG 图
→ 查看最终结果
```

现在，系统被重新定义为一个“智能体工程工作台”：

```text
Projects
→ Create Mission
→ Run
→ Mission Workspace
→ Graph / Tasks / Artifacts / Output / Runtime
```

换句话说：

> **一个大型任务不再只是一次输入和一次输出，而是一个可以长期存在、反复执行、产生中间产物、查看历史版本、恢复失败节点、追踪资源与通信的工程。**

这也是整个设计最重要的比喻：

- `Mission` 像一个工程项目；
- `ACG` 像工程内部的构建/依赖图；
- `SemanticTask` 像工程步骤；
- `Artifact` 像真正生成出来的文件或产物；
- `Run` 像一次工程构建版本；
- `Attempt` 像某一步的一次真实执行；
- `Checkpoint` 像一个恢复点。

因此，知弈的界面不再围绕“结果页”组织，而是围绕**工程、步骤、产物和运行过程**组织。

---

# 1. 为什么要重构

## 1.1 旧页面的问题不是不好看，而是产品语义不够统一

早期 ACG 页面承担了太多职责：

- 创建任务；
- 展示任务配置；
- 展示 ACG 图；
- 展示结果；
- 展示通信；
- 展示资源；
- 展示审计；
- 展示历史 Run；
- 展示调度轨迹。

这些功能本身都合理，但全部堆在同一个页面后，用户会遇到两个问题：

### 问题 A：主内容互相抢空间

例如 ACG 图和最终答案都需要较大的阅读区域，但旧页面把它们上下堆叠：

```text
Graph
↓
Result
↓
Trace
↓
更多模块
```

结果就是：图看不清，答案也看不清。

### 问题 B：系统越来越像 Dashboard

每增加一种能力，就新增一张 Card、一个指标区或一个详情块。功能虽然越来越多，但页面越来越像后台管理系统，而不是一个真正用于操作智能体工程的专业工作台。

因此，这次重构不是“继续堆更漂亮的卡片”，而是重新定义整个空间模型。

---

# 2. 核心设计思想：Mission 就是一个工程

这是整轮设计的总原则。

用户创建一个 Mission，本质上是在创建一个工程项目。例如：

> IC-200 智能装配生产线实施方案

它不会因为第一次运行结束就消失。这个 Mission 可以拥有多个 Run：

```text
Mission
├─ Run 001
├─ Run 002
└─ Run 003
```

每个 Run 都代表这个工程的一次执行/构建版本。

这使得“重新运行”与“重新创建任务”被彻底区分：

- **重新创建 Mission**：新的工程；
- **重新运行 Run**：同一工程的新构建版本。

因此用户真正操作的是一个持续存在的工程，而不是一条孤立的任务记录。

---

# 3. ACG 在新模型中的位置

ACG 仍然是知弈 AgentOS 的核心能力，但它不再是整个产品的顶层页面。

新的定义是：

```text
Mission = Project
Run = 一次工程构建 / 执行版本
ACG = Build / Dependency Graph
SemanticTask = 稳定逻辑步骤
Attempt = 某一步的真实执行实例
Artifact = 某一步产生的正式工程产物
Checkpoint = 恢复点
```

因此，用户打开一个 Mission，就像打开一个工程；打开：

```text
graph.acg
```

则是在查看这个工程的执行结构。

这使 ACG 从“一个页面”变成了一个真正的**工程对象**。

---

# 4. 用户眼中的 Mission Workspace

用户打开一个 Mission 后，看到的不是传统任务详情，而是一个类似工程目录的 Workspace：

```text
Mission
├─ OVERVIEW
│  ├─ graph.acg
│  └─ mission.md
│
├─ STEPS
│  ├─ 01 任务理解与范围界定
│  ├─ 02 需求与约束分析
│  ├─ 03 产能与节拍计算
│  └─ ...
│
├─ OUTPUT
│  └─ final.md
│
└─ RUNS
   ├─ run_003
   ├─ run_002
   └─ run_001
```

这里最重要的一点是：

> **这个“文件树”看起来像工程目录，但它不是操作系统真实文件夹。**

它只是 Runtime 状态的一种工程化投影。

这样既能给用户熟悉的“工程/文件”认知，又不会让文件系统成为新的业务真源。

---

# 5. Workspace 不是第二套真源

底层真正可信的数据仍然来自：

- Mission
- WorkflowRun
- SemanticTask
- TaskPlan
- Attempt
- Artifact
- RunArtifactBinding
- ContentManifest
- RuntimeGraph / ACGExecutionGraph
- Provenance
- Trace
- Checkpoint

Workspace 只做：

```text
真实 Runtime / Identity / Artifact 状态
                ↓
MissionWorkspaceProjection
                ↓
前端 Project Explorer / Editor / Inspector
```

因此本轮一直坚持一个底线：

> **不新增 Workspace Store，不创建第二套 Workspace 数据库，不让前端文件树成为业务真源。**

这保证了 UI 永远是系统真实运行状态的投影，而不是另外维护一套“看起来正确”的状态。

---

# 6. STEPS 到底是什么

这是本轮最关键的一次模型修正。

完整 ACG Graph 中可能同时存在：

- `step` 节点；
- `agent` 节点；
- `memory` 节点；
- `evidence` 节点；
- `control` 节点。

因此：

```text
Graph Nodes ≠ Workspace Steps
```

同时，某个执行步骤可能没有正式 Artifact，因此：

```text
Artifact 数量 ≠ Workspace Steps
```

最终统一为：

```text
SemanticTask
= Workspace 中的逻辑步骤

Artifact
= 某个步骤真实产生的正式产物
```

一个没有 Artifact 的 Task 依然存在：

```text
08 方案比较
└─ 当前没有独立 Artifact
```

而一个 Task 也可能产生多个 Artifact：

```text
07 设备与人员规划
├─ primary.md
├─ equipment.csv
└─ assumptions.json
```

这样 Workspace 显示的永远是事实，而不是为了让界面“看起来完整”去人为制造文件。

---

# 7. 为什么 Artifact 不能等于 Task

从用户视角看，“一个步骤一个文件”非常直观，但底层不能把两者强绑定。

因为未来一个步骤可能：

- 不产生文件；
- 产生一个 Markdown；
- 同时产生 JSON、CSV、PDF；
- 产生代码；
- 只产生状态和 Trace；
- 只修改已有 Artifact。

因此正确关系是：

```text
SemanticTask
   ↓ executes
Attempt
   ↓ produces
Artifact[]
```

Workspace 可以把 Artifact 显示成文件，但底层仍然保持 Task 与 Artifact 解耦。

---

# 8. Artifact 的核心语义

Artifact 是一个正式、可追踪、不可变的工程产物。

其逻辑身份被拆成两层：

```text
artifactId
= 这一次具体产生的不可变版本

artifactKey
= 某个 SemanticTask 下跨 Run 稳定的逻辑产物槽位
```

例如：

```text
semanticTaskKey = equipment_staff_plan
artifactKey = primary
```

不同 Run 中可能产生：

```text
Run 001 → artifact_a
Run 002 → artifact_b
Run 003 → artifact_c
```

它们是同一个逻辑产物槽位的不同真实版本。

这为未来的：

- Artifact diff；
- Run compare；
- 历史版本；
- 增量重建；

提供了稳定基础。

---

# 9. 中央工作区为什么采用 Editor 模型

旧页面把 Graph、Result、Trace 等内容纵向堆叠，这是一种典型网页思维。

新的 Workbench 改为 Editor 模型：

```text
Editor Tabs
├─ graph.acg
├─ TaskEditor
├─ ArtifactEditor
├─ MissionEditor
└─ Virtual Editors
```

核心原则：

> **同一时刻只让一个 Primary Content 占据主工作区。**

因此：

- Graph → `GraphEditor`
- SemanticTask → `TaskEditor`
- Artifact → `ArtifactEditor`
- Mission 概览 → `MissionEditor`
- Resource Topology / Provenance / Run Compare → 未来的 Virtual Editor

这样图、任务说明和最终产物不再争抢空间。

---

# 10. Workbench 的四个核心空间

整个 Mission Workspace 最终被固定为四个主要空间：

```text
Primary Sidebar
= 工程结构

Editor
= 当前主内容

Secondary Sidebar
= 当前对象的多视角观察

Bottom Panel
= 完整运行过程
```

## 10.1 Project Explorer

负责：

- Overview
- Steps
- Output
- Runs

它回答：

> “这个工程里有什么？”

## 10.2 Editor

负责：

- Graph
- Task
- Artifact
- Mission
- 深度分析视图

它回答：

> “我现在主要在看什么？”

## 10.3 Secondary Sidebar

右侧不再只是固定的属性表，而是多个观察视角：

```text
运行 | 资源 | 通信 | 审计 | 上下文
```

它回答：

> “当前对象还能从哪些角度理解？”

## 10.4 Bottom Panel

负责完整运行过程：

- Problems
- Communication
- Trace
- Events
- Tool Calls
- Logs（后续）

它回答：

> “这个 Run 到底是怎么运行的？”

---

# 11. 为什么 Resource、Communication 不再全部做成独立页面

本轮形成了一条很重要的判断规则：

```text
Editor
= 主内容 / 深度分析

Secondary Sidebar
= 当前对象摘要和属性

Bottom Panel
= 完整运行过程
```

例如 Communication：

- Bottom Panel：完整时间序列；
- Secondary Sidebar：当前 Task / Node 的通信摘要；
- Editor：必要时打开 Communication Trace 深度分析。

Resource 同理：

- 全局 Resource Center：系统拥有的资源；
- Secondary Sidebar：当前 Run / Node 实际使用的资源；
- Virtual Editor：复杂资源拓扑分析。

这避免了“一个模块就做一个页面”的后台系统思维。

---

# 12. Secondary Sidebar：AgentOS 的侧面观察系统

右侧栏被正式定义为 Secondary Sidebar，而不是传统 Inspector。

默认 View 可以包括：

```text
运行
资源
通信
审计
上下文
```

这些 View 会根据当前选择对象动态变化。

例如用户打开 `graph.acg`：

```text
运行视图
├─ Run 状态
├─ Graph 信息
├─ 节点数 / 边数
└─ 运行观测摘要
```

当用户选中一个 SemanticTask：

```text
任务视图
├─ Identity
├─ Execution
├─ Resource
├─ Artifacts
└─ Communication
```

因此右侧栏不是固定元数据面板，而是当前对象的多视角观察器。

---

# 13. Bottom Panel：完整运行观测

Bottom Panel 的定位不是“放剩下的内容”，而是专门承载运行过程。

例如：

```text
Problems | Communication | Trace | Events | Tool Calls
```

这些信息有三个共同点：

1. 都与当前 Run 绑定；
2. 通常是时间序列或观测记录；
3. 不应该长期占据主 Editor。

因此 Bottom Panel 类似专业 IDE 中的 Terminal / Problems / Output，但内容完全针对 Agent Runtime。

---

# 14. Contribution System：为什么要做内部插件化

随着 Resource、Communication、Trace、Audit、Memory 等能力恢复，如果继续全部写进 `MissionWorkspaceView`，最终一定会变成新的巨型组件。

因此建立了轻量的 Native Workbench Contribution System。

概念上：

```text
WorkbenchContribution
├─ Editor Contribution
├─ Inspector / Secondary Sidebar Contribution
├─ Bottom Panel Contribution
├─ Activity / View Contribution
└─ Command Contribution
```

当前原则：

- 静态注册；
- typed；
- deterministic；
- trusted native modules。

明确不做：

- 第三方插件市场；
- dynamic extension loading；
- extension host；
- plugin sandbox；
- runtime plugin installation。

Contribution 的唯一目标是：

> **以后新增一种 AgentOS 能力，不需要修改 Workspace 核心 DOM。**

---

# 15. WorkbenchContext：统一当前选择上下文

Contribution 需要知道“用户现在正在看什么”。

因此定义统一 Workbench Context，典型包括：

```text
missionId
runId
activeEditorId
selectedSemanticTaskKey
selectedArtifactId
selectedAcgNodeId
historicalMode
```

这只是 UI Selection Context。

它不复制 Runtime 真源，不把 Run 状态、Trace、Artifact 正文重新存进前端全局状态。

原则是：

> **Context 负责告诉 UI “当前选择是谁”，后端权威状态负责告诉 UI “这个对象是什么”。**

---

# 16. Runtime Observation Adapter

Communication、Trace、Events、Tool Calls 都依赖当前 Run。

如果每个 Panel 各自启动自己的 polling / SSE，会出现：

- 重复请求；
- listener 泄漏；
- 切换 Run 后旧数据残留；
- stale response 覆盖新状态。

因此使用统一 Runtime Observation Adapter：

```text
Current Run Context
        ↓
RuntimeObservationAdapter
        ├─ communication
        ├─ trace
        ├─ events
        ├─ toolCalls
        └─ problems
```

切换 Run 时统一：

```text
取消旧请求
→ 清理旧状态
→ 绑定新 runId
→ 重新加载 / 订阅
```

这样所有 Runtime 面板始终围绕同一个 Run 生命周期工作。

---

# 17. UI 必须忠实于真实 Runtime

这次设计有一条非常严格的原则：

> **UI 是运行事实的投影，不是运行事实的制造者。**

具体包括：

- Resource health 为 `unknown`，UI 就显示 Unknown；
- Communication reliable store 没数据，就从 Provenance / Trace 做只读 projection，并标明来源；
- Tool Call 没真实 duration，就显示“未观测”；
- Legacy Artifact 无法证明 stable identity，就显示 legacy；
- 没 Artifact 的 Task 仍然显示 Task，但绝不伪造 `.md` 文件；
- Final Artifact 只有被明确证明为 final/deliverable 时才进入 Output。

这种真实性对 AgentOS 尤其重要，因为系统未来要强调：

- 可解释；
- 可追踪；
- 可审计；
- 可恢复。

如果 UI 自己“补齐”不存在的数据，这些能力就失去可信度。

---

# 18. 运行历史：像版本，而不是重复项目

一个 Mission 可以有多个 Run，但 Project List 中：

```text
one Mission = one Project row
```

Run 历史只属于当前 Mission：

```text
RUNS
├─ run_003  current
├─ run_002
└─ run_001
```

点击历史 Run 时，整个 Workspace 切换为该历史投影，并显示：

```text
Read-only / Historical
```

而不是在 Explorer 同时展开三套完整文件树。

这使 Run 更像工程版本历史，而不是三个重复项目。

---

# 19. 新建工程的产品语义

旧入口：

```text
新建 ACG 任务
```

已经不再适合新的产品模型。

新的用户认知应是：

```text
新建工程 / Create Mission
```

用户点击“创建并运行”后：

```text
Create Mission
→ Create first Run
→ 立即进入 Mission Workspace
```

不要在创建页等待整个任务结束。

正确体验是：

> **工程一创建就打开，运行过程在工程内部实时发生。**

---

# 20. Graph 与 Task / Artifact 的双向关系

Workbench 不只是“文件树 + 图”。两者必须能互相定位。

## Graph → Task

Graph Node 带有稳定 `semanticTaskKey`：

```text
Graph Node
→ semanticTaskKey
→ Workspace Task
→ TaskEditor
```

## Task → Graph

TaskEditor 中可以：

```text
在图中定位
→ 打开 graph.acg
→ focus 对应 semanticTaskKey
```

## Task → Artifact

Task 下面展示真实 Artifact：

```text
Task
├─ primary.md
└─ assumptions.json
```

## Artifact → Graph

Artifact 通过 `semanticTaskKey` 找到生产它的逻辑步骤，再定位 Graph Node。

这形成真正的工程闭环，而不是几个互相独立的页面。

---

# 21. 视觉设计总纲

视觉层面最终不是纯 VS Code，也不是 Dashboard。

最终风格被定义为：

> **Workbench 骨架 + Apple-style Section + 知弈浅紫灰品牌体系。**

核心关键词：

- 克制；
- 锐利；
- 秩序；
- 轻盈；
- 有板块感；
- 小而精致。

---

# 22. 为什么从“大量 Card”走到“Section Surface”

早期 Dashboard 的问题是：

- Card 太多；
- Card 套 Card；
- 指标墙严重；
- 视觉层级过度。

初版 Workbench 又走到另一个极端：

- 全白；
- 横线很多；
- 像 Debug Tool；
- 缺少产品感。

最终规则是：

> **一级区域可以有 Surface，Surface 内不要继续 Card 套 Card。**

允许使用柔和 Section 的区域包括：

- Graph Surface；
- Task 内容 Section；
- Inspector Section；
- Runtime Bottom Panel；
- Project Summary。

视觉特征：

- 浅紫灰 Shell；
- 白色内容 Surface；
- 8~10px 柔和圆角；
- 极弱边框；
- 极弱阴影；
- 蓝紫仅用于 active / selected / command。

---

# 23. Explorer 视觉原则

Explorer 要同时满足两点：

1. 像工程树；
2. 能快速扫描 20~50 个步骤。

因此采用：

- 行高约 30~34px；
- displayOrder 独立窄列；
- 状态用 ✓ / ● / ○ / ! 等轻图标；
- 不重复显示大量 `completed`；
- selected row 使用浅紫背景 + 细 accent bar；
- Artifact child 进一步缩进；
- Project Header 有轻微板块感，但不做大品牌 Card。

目标：

> **高密度，但不是“裸文件树”。**

---

# 24. TaskEditor 视觉原则

TaskEditor 不能像数据库详情表。

信息优先级应该是：

```text
这一步要做什么
↓
执行情况
↓
产物
↓
技术身份
```

因此页面顺序推荐：

```text
Task Header
Objective
Execution Summary
Artifacts
Runtime / Identity Metadata
```

Objective 是主要阅读内容；`semanticTaskKey / taskId / acgNodeId` 等技术字段后置并弱化。

---

# 25. Inspector / Secondary Sidebar 视觉原则

右侧采用 Apple-style grouped sections，而不是数据库 property table。

例如：

```text
运行状态
图信息
执行信息
资源
运行观测
```

每个 Section：

- 白色或柔和 Surface；
- 8~10px radius；
- soft border；
- 12~14px padding；
- 8~10px section gap。

禁止：

- 每个字段一个 Card；
- 大型 KPI wall；
- 强阴影。

---

# 26. Bottom Panel 视觉原则

Bottom Panel 是完整 Runtime Surface：

```text
Problems | Communication | Trace | Events | Tool Calls
```

它不是网页表格附属区。

要求：

- 独立 Surface；
- 自己的 TabBar；
- 自己滚动；
- 可折叠；
- 可上下调整高度；
- active tab 明确；
- timestamp 弱、event type 强、summary 次之；
- duration/status 右对齐。

---

# 27. App Shell：统一成桌面 Workbench

顶部栏的目标不是网页 Header，而是应用级 Shell。

最终职责：

```text
App identity
+ global menu
+ back/forward
+ workspace context
+ search/command
+ global actions
```

左侧 Sidebar 只负责产品导航，不重复品牌。

---

# 28. 顶部栏核心视觉：Small, Precise, Quiet

所有元素都做小、做精致：

- Top Bar：约 40~42px；
- Logo：18~20px；
- Menu：12.5~13px；
- Icon：14~15px；
- Hit area：28~30px；
- Search：约 30px 高；
- Radius：4~6px；
- Hover：极轻；
- 无强阴影；
- 不做大型品牌块。

核心关键词：

> **Small, precise, quiet, professional.**

---

# 29. 品牌与顶部栏去重

品牌只保留一个主要展示位置。

推荐顶部：

```text
[小 Logo] 文件 编辑 查看 运行 帮助 ...
```

而左侧不再重复：

```text
[Logo] 知弈
```

顶部负责应用身份和全局操作，左侧负责导航。

这样可以避免：

- 双 Logo；
- 双“知弈”；
- Top Bar 与 Sidebar 同时抢品牌注意力。

---

# 30. Shell 配色

顶部不做与整体割裂的纯 VS Code 深蓝。

采用同色系低饱和蓝灰紫：

```text
Top Bar
= deep desaturated blue-gray-purple

Workbench
= light purple-gray

Surface
= white

Accent
= blue-violet
```

视觉上形成：

```text
深色 App Chrome
→ 浅色 Workbench Shell
→ 白色内容 Surface
```

但全部属于同一色彩家族。

---

# 31. 独立滚动与可缩放

Workbench 不是普通页面，因此必须长期保持：

- Explorer 独立滚动；
- Editor 独立滚动；
- Secondary Sidebar 独立滚动；
- Bottom Panel 独立滚动；
- body 不作为主要页面滚动容器。

Pane 支持：

- 左右 resize；
- collapse / restore；
- Bottom Panel vertical resize；
- responsive auto-hide；
- 用户 collapse 与 auto-hide 状态分离。

这样用户操作感更接近桌面软件，而不是网页。

---

# 32. 响应式策略

优先级固定为：

```text
Main Editor
> Primary Sidebar
> Secondary Sidebar
```

窗口过窄：

1. 先 auto-hide Secondary Sidebar；
2. 再 auto-hide Primary Sidebar；
3. 始终优先保证 Editor 可用。

自动隐藏状态不能覆盖用户主动 collapse 状态，也不能错误持久化。

顶部栏在窄屏时始终保持单行，通过：

- context ellipsis；
- search 收缩；
- actions 隐藏；
- menu overflow；

而不是换行。

---

# 33. 历史兼容与诊断

Legacy 数据必须诚实降级。

例如：

- 无 canonical semanticTaskKey → legacy；
- 无可解析 TaskPlan snapshot → `PLAN_SNAPSHOT_UNRESOLVED`；
- legacy Artifact 无法和 Graph 证明对应关系 → 不启用 Graph 定位。

这些诊断不应该永久占 Project Explorer 顶部，而应统一进入：

```text
Problems Panel
```

Explorer 只负责工程结构。

---

# 34. 为什么这套设计比简单“复刻 VS Code”更合理

VS Code 的核心对象是文件和代码。

知弈的核心对象是：

```text
Artifact + Runtime Object
```

因此知弈既有“像文件”的对象：

- graph.acg
- mission.md
- final.md
- JSON / CSV / PDF Artifact

也有大量没有物理文件的 Virtual Editor：

- TaskEditor
- Resource Topology
- Communication Trace
- Provenance Graph
- Run Compare
- Memory Timeline

所以知弈不是代码 IDE，而是：

> **Agent Runtime Engineering Workbench。**

---

# 35. 技术实现：Workspace Projection

建议的数据读取边界：

```text
GET /agentos/v2/missions/{missionId}/workspace
GET /agentos/v2/missions/{missionId}/workspace?runId={runId}
```

典型 Projection：

```text
MissionWorkspaceProjection
├─ mission
├─ activeRun
├─ runs[]
├─ entries[]
├─ graphNodes[]
└─ diagnostics[]
```

Entry 类型包括：

```text
folder
graph
virtual_document
task
artifact
run
```

其中：

- `graph.acg` 是 virtual graph entry；
- `mission.md` 是 virtual document；
- Task 来自 SemanticTask；
- Artifact 来自 RunArtifactBinding + Artifact；
- Run section 来自历史 Run。

---

# 36. 技术实现：稳定 Entry Identity

稳定 UI identity 不依赖 `acgNodeId`。

推荐：

```text
Task Entry
= task:{semanticTaskKey}

Artifact Entry
= task:{semanticTaskKey}:{artifactKey}
```

原因：

- `semanticTaskKey` 跨 Run 稳定；
- `acgNodeId` 是某个 Blueprint / Run 内的执行身份，可能变化；
- `artifactId` 是某次具体产物版本，不适合做跨 Run editor identity。

这样切换 Run 时，同一个 Editor Tab 可以重新绑定不同版本 Artifact，而不需要创建新的逻辑 Tab。

---

# 37. 技术实现：三层 Task Identity

身份必须严格区分：

```text
semanticTaskKey
= 跨 Run 稳定的逻辑任务身份

acgNodeId
= 某次 Blueprint / Graph 内的执行节点身份

attemptId
= 某次真实执行实例身份
```

Workspace 稳定对象使用 `semanticTaskKey`，Runtime 执行仍使用 `acgNodeId / attemptId`。

---

# 38. 技术实现：Artifact 与 ContentManifest 边界

Artifact 不存正文。

建议：

```text
Artifact
= domain identity + producer relationship

ContentManifest
= immutable content storage
```

Artifact 典型字段：

```text
artifactId
missionId
originRunId
taskId
semanticTaskKey
artifactKey
acgNodeId
producerAttemptId
name
artifactType
mediaType
contentRef
checksum
createdAt
metadata
```

其中：

```text
contentRef → ContentManifest
```

这样不会建立第二套 Content Store。

---

# 39. 技术实现：RunArtifactBinding

Artifact 本体保持 immutable，不把：

- stale
- reused
- current
- invalidated

写进 Artifact 本身。

Run 对 Artifact 的使用关系由 `RunArtifactBinding` 表达：

```text
runId
semanticTaskKey
artifactKey
artifactId
disposition
sourceRunId
```

核心约束：

```text
UNIQUE(run_id, semantic_task_key, artifact_key)
```

未来 disposition 可以表达：

```text
GENERATED
REUSED
```

---

# 40. 技术实现：Contribution Registry

Contribution Registry 必须保持：

- lightweight；
- typed；
- deterministic；
- isolated testable instance；
- explicit composition root。

建议概念：

```text
WorkbenchContribution
├─ editors[]
├─ inspectors[]
├─ panels[]
├─ activityViews[]
└─ commands[]
```

不要通过组件 import side effect 自动注册。

Composition root 应明确：

```text
createWorkbenchRegistry()
register(projectContribution)
register(resourceContribution)
register(runtimeContribution)
```

---

# 41. 技术实现：Secondary Sidebar Contribution

右侧 View 不应硬编码在 `MissionWorkspaceView`。

建议最小接口：

```text
id
title
order
when(context)
component
```

例如：

```text
ProjectContribution → 运行
ResourceContribution → 资源
RuntimeContribution → 通信
AuditContribution → 审计
MemoryContribution → 上下文
```

当前 Workspace 只负责解析并渲染适用 View。

---

# 42. 技术实现：Runtime Observation

通信和运行观测必须区分真实来源。

例如 Communication 当前可以来自：

```text
Provenance
+
communication-related Trace
```

Normalized item 应保留：

```text
source = provenance | trace
```

这样未来 reliable communication store 真正有数据后，可以自然替换或合并，而不用重做 UI contract。

---

# 43. 技术实现：历史 Run

历史 Run 查询：

```text
/workspace?runId=run_xxx
```

切换后：

- 整个 Workspace 切换对应 Projection；
- graph.acg 切换历史 Graph；
- Task / Artifact editor 重新绑定对应版本；
- 不存在的 Artifact 明确显示 Not available；
- 所有 Runtime Panel 切换当前 runId；
- 全程 Read-only。

不要让旧异步请求覆盖新 Run 状态。

---

# 44. 下一阶段：Incremental Rebuild

这一轮前端重构最终是在为下面这条能力做准备：

```text
选择 SemanticTask
→ 从此步骤重新运行
→ descendants(selectedTask)
→ 创建 Child Run
→ 复用未受影响 Artifact
→ selected + affected descendants 重新执行
```

未来用户操作的是 SemanticTask，而不是某个具体 Artifact 文件。

原因：

- Task 是逻辑执行单元；
- Artifact 是 Task 的结果；
- 增量重建要计算的是依赖图中的受影响节点。

因此最终能力链路是：

```text
Mission
→ SemanticTask
→ Attempt
→ Artifact
→ Run history
```

而 Workspace 已经为这个模型提供完整交互基础。

---

# 45. 设计约束：未来不要重新走回去

后续开发应明确避免以下退化：

## 不要重新变成 Dashboard

禁止：

- 每增加一个能力就加一张大型 Card；
- Graph、Result、Trace 再次纵向堆叠；
- KPI wall；
- 大量 metric tiles。

## 不要建立第二套前端真源

禁止：

- Workspace Store 复制 Runtime 状态；
- 每个 Panel 自己维护一份 Run；
- UI 自己猜 Artifact / Task 对应关系。

## 不要过度插件化

暂时禁止：

- Marketplace；
- dynamic plugin loading；
- extension host；
- sandbox；
- third-party runtime extension。

Native Contribution 只用于前端组合解耦。

## 不要继续反复换 Shell

Workbench 结构和视觉体系完成后应冻结。

后续 UI 修改应围绕新功能做局部增加，而不是重新设计整个页面。

---

# 46. 给不同角色看的设计重点

## 对普通用户

你可以把知弈理解成：

> 一个“会自己执行工作的智能工程项目”。

你创建一个项目，系统自动拆步骤、执行、产生产物；你可以查看每一步发生了什么，也可以看到最终交付物和历史运行版本。

## 对产品经理

核心不是聊天，而是：

```text
Mission lifecycle
+ Task lifecycle
+ Artifact lifecycle
+ Run lifecycle
```

Workbench 只是把这些生命周期变成可操作的产品体验。

## 对 UI / UX 设计师

核心空间规则：

```text
Explorer = 工程结构
Editor = 主内容
Secondary Sidebar = 当前对象视角
Bottom Panel = 运行过程
```

视觉规则：

```text
Workbench skeleton
+ Apple-style section
+ small / precise desktop shell
```

## 对前端工程师

不要在 `MissionWorkspaceView` 硬编码能力。

优先使用：

- Workspace Projection；
- Workbench Context；
- Contribution Registry；
- Runtime Observation Adapter。

## 对后端工程师

Workspace 不应要求第二套业务模型。

后端应提供：

- stable identity；
- reliable projection；
- Artifact lineage；
- Run history；
- Runtime observation；

前端只消费，不猜测。

---

# 47. 核心术语表

| 术语                 | 通俗解释       | 技术含义                                 |
| -------------------- | -------------- | ---------------------------------------- |
| Mission              | 一个工程项目   | 长期稳定的任务聚合根                     |
| Run                  | 一次运行版本   | Mission 的一次完整执行                   |
| ACG                  | 工程执行图     | Run 内的依赖/计算图                      |
| SemanticTask         | 一个逻辑步骤   | 跨 Run 稳定的任务身份                    |
| Attempt              | 一次真实尝试   | 某 Task 的具体执行实例                   |
| Artifact             | 正式产物       | Attempt 产生的不可变输出对象             |
| artifactKey          | 逻辑产物槽位   | 同一 Task 下跨 Run 稳定的产物身份        |
| ContentManifest      | 内容存储对象   | Artifact 正文/fragment/checksum 的存储   |
| Workspace Projection | 工程视图       | Runtime 状态的只读前端投影               |
| Editor               | 主内容区       | Graph/Task/Artifact/Virtual Editor       |
| Secondary Sidebar    | 侧面观察区     | 当前对象的运行/资源/通信/审计/上下文视角 |
| Bottom Panel         | 运行观测区     | Problems/Trace/Events/Tool Calls 等      |
| Contribution         | 内部扩展点     | Native UI 模块注册机制                   |
| Incremental Rebuild  | 从中间重新构建 | 复用未受影响结果，仅重跑受影响子图       |

---

# 48. 最终设计原则

可以浓缩为十二条：

1. **Mission 是工程，不是一次任务记录。**
2. **ACG 是工程内部的执行图，不是产品顶层页面。**
3. **SemanticTask 是稳定逻辑步骤，Artifact 是真实产物。**
4. **Workspace 是 Runtime 的只读工程投影，不是第二真源。**
5. **Editor 展示主内容，Secondary Sidebar 展示当前对象视角，Bottom Panel 展示运行过程。**
6. **Graph、Task、Artifact 必须可以互相定位。**
7. **能力通过 Contribution 挂入 Workbench，而不是继续堆页面。**
8. **Runtime Observation 统一生命周期，避免多套 polling 和 stale state。**
9. **UI 必须忠实于真实 Runtime，不伪造数据补齐界面。**
10. **保留 Workbench 骨架，同时使用 Apple-style Section 恢复板块感和产品感。**
11. **App Shell 与所有控件都走“小、精致、克制”的桌面工具风格。**
12. **视觉和 Workbench 架构冻结后，后续重点转回 Runtime 能力。**

---

# 49. 一句话总结

> **这轮前端重构的本质，是把知弈从“展示 ACG 执行结果的 Dashboard”，重构为“围绕 Mission、SemanticTask、Artifact 与 Run 组织的 Agent Runtime 工程工作台”；它借鉴 IDE 的空间逻辑，但并不复制 VS Code，而是通过 Apple-style 板块、紧凑桌面 Shell 和 Native Contribution 机制，形成一套服务于真实、可追踪、可恢复、可持续演化智能任务的产品界面。**

---

# 50. 最终愿景

如果把整个设计再抽象一层，知弈 AgentOS 想做的并不是“一个更复杂的聊天页面”。

它真正希望成为的是：

> **一个让人能够像操作软件工程一样，操作复杂智能体任务的 Runtime Workbench。**

用户可以：

- 打开一个 Mission；
- 查看它的执行图；
- 查看每一个逻辑步骤；
- 查看真实产物；
- 查看资源、通信、Trace、审计和上下文；
- 切换历史 Run；
- 未来从某个步骤重新构建；
- 比较新旧产物；
- 恢复失败执行；
- 审计整个过程。

当这些能力都围绕同一个 Workspace 模型发生时，知弈才真正从“Agent 应用界面”走向“AgentOS 工程工作台”。
