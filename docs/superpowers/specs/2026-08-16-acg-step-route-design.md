# ACG Step 路线图设计

## 目标

将 ACG 可视化的默认呈现从全量异构拓扑改为以 Step 为核心的执行路线，让用户快速理解任务顺序、并行步骤和当前状态。

## 范围

- 在 `AcgTopologyGraph` 中新增并默认使用“Step 路线”视图。
- 保留现有“全图”视图，作为辅助排障与审计能力。
- 不改变后端 ACG API、不重写数据结构，也不删除既有血缘和导出能力。
- 对话历史默认折叠需求已确认，但本轮仅实现 ACG 可视化，避免将独立页面改动混入同一个发布单元。

## 交互与信息层级

默认的“Step 路线”仅将 `nodeType === 'step'` 节点放在主画布：

1. 依赖边从左到右连接 Step；没有 Step 依赖时不虚构连接。
2. Step 卡片显示序号、名称、状态、执行 Agent 和时长。
3. 相同前置依赖的 Step 并列显示，表达并行阶段；汇合后继续主线。
4. 点击 Step 后在右侧详情显示目标、能力、Binding、运行历史、错误或输出摘要，以及关联 Agent、Skill、Memory、Evidence、Control 节点。
5. 顶部提供“Step 路线 / 全图”切换。全图复用现有边筛选、主执行链、全屏和节点详情能力。

## 数据映射

- 路线节点：`AcgBlueprint.nodes` 中的 Step。
- 路线边：两端均为 Step 的 `dependency` 边。
- 阶段：按 Step-only dependency 图的拓扑层级计算；无入边的 Step 为第一阶段，后继 Step 取所有前置阶段的最大值加一。
- 详情关联：通过 blueprint 边收集选中 Step 的入边与出边，按节点类型分组。

## 兼容与验收

- 没有 Step 依赖时，仍展示可点击的 Step 卡片并标为独立 Step。
- 旧 Run 缺少 `stepStates` 时使用 `completedStepIds` 表示完成状态。
- 没有 Step 时显示空态，并允许切换至全图。
- 小屏幕允许路线横向滚动，详情面板移动到路线下方。
- 默认展示 Step 路线；并行 Step 同阶段并列；全图的既有操作仍可使用。
