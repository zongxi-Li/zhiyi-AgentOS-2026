# 资源中心与历史记录整合设计

## 目标

将角色管理、联邦管理、模型管理统一纳入资源中心；将 ACG 历史记录统一纳入历史记录；移除对应的独立页面入口，并为整合后的页面提供统一的文字横幅标题和更宽的桌面内容区域。

## 已确认的用户体验

资源中心 `/agentos/resources` 是资源相关能力的唯一入口，Tab 包括：

1. 资源概览
2. 角色管理
3. 联邦管理
4. 模型管理

历史记录 `/history` 是历史能力的唯一入口，Tab 包括：

1. 对话历史
2. 文件历史
3. ACG 历史

每个 Tab 通过 URL 查询参数保持可分享和可恢复的状态：

- `/agentos/resources?tab=overview|roles|federated|models`
- `/history?tab=conversations|files|acg`

进入不带参数的页面时分别默认 `overview` 和 `conversations`。

## 路由与导航

主侧栏只保留资源中心和历史记录，不再显示角色管理、联邦管理、模型管理和 ACG 历史记录的独立入口。

旧地址保留为兼容重定向，不再挂载旧页面组件：

- `/roles` → `/agentos/resources?tab=roles`
- `/federated-learning` → `/agentos/resources?tab=federated`
- `/federated-models` → `/agentos/resources?tab=models`
- `/agentos-console` → `/history?tab=acg`

重定向保留登录保护和已有的浏览器/桌面历史行为。`/create-role` 仍保留，因为角色管理面板需要继续进入角色创建流程。

## 组件边界

新增通用标题组件 `apps/frontend/src/components/app/WorkspacePageHero.vue`，负责英文眉标题、中文标题、描述和右侧操作插槽。标题使用真实 HTML 文本，不生成图片文字，以保留无障碍、搜索和响应式能力。

资源中心保留页面容器，并拆分为以下内部功能组件：

- `apps/frontend/src/components/resource-center/ResourceOverviewPanel.vue`
- `apps/frontend/src/components/resource-center/RoleManagementPanel.vue`
- `apps/frontend/src/components/resource-center/FederatedManagementPanel.vue`
- `apps/frontend/src/components/resource-center/ModelManagementPanel.vue`

这些组件分别迁移现有资源概览、角色管理、联邦学习和模型管理页面的业务逻辑，继续使用原有 Store、API、操作反馈和加载/错误状态。旧页面的完整页面壳层、重复标题和独立背景不迁移。

历史记录保留现有对话历史和文件历史内容，新增：

- `apps/frontend/src/components/history/AcgHistoryPanel.vue`

该组件迁移 ACG 历史页面的运行筛选、运行列表、运行详情、取消/刷新、审计信息和进入 ACG/Chat 操作，并复用现有运行状态组件与 API。

## 页面布局

资源中心和历史记录均使用统一的页面内容容器：

- 桌面最大宽度：`1400px`
- 容器宽度：`min(100%, 1400px)`
- 桌面左右留白由容器自动居中控制
- 中小屏保留现有 `calc(100% - ...)` 和断点布局

标题横幅统一使用相同的上下间距、边框、字体层级和操作区布局。资源中心、历史记录及各 Tab 不再重复渲染旧页面标题。

ACG 历史的运行列表和详情仍保留其内部可拖拽面板宽度能力；它只负责内容区域，不再控制外层页面宽度。

## 状态和 URL 同步

资源中心和历史记录各自定义有限的 Tab 类型，并在挂载时将未知值归一化为默认 Tab。Tab 点击使用 `router.replace` 更新查询参数，不触发完整页面导航；浏览器前进/后退时根据路由查询参数恢复 Tab。

刷新按钮只刷新当前 Tab 所属数据。搜索、筛选、选中项等局部状态不写入 URL，避免把运行详情和敏感工作区状态扩大为公共链接契约。

## 删除和迁移范围

迁移完成后删除以下独立页面文件及其仅服务于独立页面的测试：

- `apps/frontend/src/views/RoleView.vue`
- `apps/frontend/src/views/FederatedLearningView.vue`
- `apps/frontend/src/views/FederatedModelManagementView.vue`
- `apps/frontend/src/views/AgentOsConsoleView.vue`

资源中心和历史记录原有测试迁移或补充为父页面/功能面板测试；不删除仍被创建流程、聊天流程或其他页面复用的组件、Store、API 和 `CreateRoleView.vue`。

## 验证策略

实施采用测试先行，按以下顺序验证：

1. 为 Tab 默认值、未知值归一化、查询参数同步和旧路由重定向添加失败测试。
2. 为统一标题组件和 `1400px` 页面宽度添加布局契约测试。
3. 迁移各功能面板后运行其原有行为测试，并补充资源中心/历史记录的 Tab 切换测试。
4. 删除旧页面入口后检查主导航、活动菜单、滚动策略和所有内部跳转引用。
5. 运行 `npm test`、`npm run build:web` 和 `git diff --check`。

## 非目标

- 不改变资源、角色、联邦、模型或运行历史的后端 API 契约。
- 不改变权限、认证、租户范围或数据加载策略。
- 不把标题文字转换为位图图片。
- 不借此重构与页面整合无关的 Store、API 或 AgentOS 运行时。
