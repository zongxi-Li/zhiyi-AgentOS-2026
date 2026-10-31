# PR-UI-02A｜Session Continuity 实施报告

日期：2026-10-31。实施范围：前端会话身份、历史恢复、本地关联迁移和 Run 展示语义。最终状态：**SELF-TESTED**。未进行独立 ACCEPT。

## 1. 现场与保护边界

- 分支 `master`；开始 HEAD `081aa3fd22903d3b73c98d1a25dc750b3f036557`。
- 开始时已有修改：`apps/agent/app/config.py`、两份 `output/release-*` 文档；新增的 PR-UI-02 审计报告。
- 实施中观察到 `SettingsView.vue` 和上述发布文档的并行修改，未写入、恢复或纳入本轮实施。
- 对 Agent 配置、原审计报告、整个 `features/mission/`、`AuthenticatedAppShell.vue` 建立 SHA256 基线。配置、原审计报告、全部 Mission Launch 文件及 Shell 均与基线一致。发布文档在执行期间发生并行变化，原样保留。
- 未执行 Reset、Checkout、Stash、Commit、Push、Merge、部署或后端数据变更。

## 2. 实际发现与问题复现

1. ChatView 原 context watcher 只维护 workspace 索引，新聊天首次获得 contextId 后未写 URL，刷新不能定位原会话。
2. Chat Store 原 loadHistory 只加载消息，未获取 Conversation 元数据，上一会话的 roleId 会残留。
3. 原历史请求没有代次保护，慢 A 请求能覆盖已恢复的 B，包括消息、contextId 和 loading。
4. 旧 Agent 会话的传输模式可能被当前视图模式覆盖；文件发送还省略了 workspaceMode。后端 `ChatStreamPersistenceService.java:37` 起按 contextId 和 workspaceMode 匹配，模式不一致可能创建另一 Conversation。
5. 直接启动任务的 draft binding 未随首次聊天 contextId 迁移，真实上下文和历史任务关联断开。
6. Chat Store、全局 reference 索引和轮询器的终态集合只覆盖 completed/failed/cancelled；部分判断混用了 status 与 phase。
7. 原恢复链虽然优先读取显式 runId，但未验证 URL missionId 与 Run 归属，也未区分已验证选择和最近 binding。
8. 历史页面初始化也会生成新的本地 draft UUID，恢复操作中没有必要。

在修改前新增两条 Store 行为测试并实际运行：均失败，分别观测到 roleId 为 `previous-role`，以及 B 恢复后 contextId 被慢请求回写为 A。日志：`%TEMP%/pr-ui-02a-red.log`。

最小方案：纯函数处理索引和选择；原 Store 局部增加历史请求代次、元数据恢复；仅在当前草稿首次发送得到 contextId 时迁移；复用现有 Run 详情和 Mission workspace GET 验证归属。未建设 Session 实体、Workspace Store 或 Session Manager。

## 3. 修改文件清单

路径均相对于 `apps/frontend/src/`：

| 文件 | 改动 |
|---|---|
| `features/workspace/session.ts`（新增） | 身份关联、别名、draft 合并、URL 增量参数、Run 选择和状态纯函数 |
| `features/workspace/session.spec.ts`（新增） | 索引多重关联、冲突保护、选择与状态行为测试 |
| `stores/chat.ts` | 历史代次保护、角色/传输模式恢复、局部 binding 迁移和别名读取 |
| `stores/chat.session.spec.ts`（新增） | 恢复竞态、模式兼容、迁移、快照与无副作用测试 |
| `stores/chat.stream.spec.ts` | 原历史恢复测试补齐现有元数据 API fixture，保留原断言 |
| `stores/workflowRuns.ts` | 原 reference 索引原位关联更新、别名持久化、共享活动状态判断 |
| `views/ChatView.vue` | context URL 同步、发送过程迁移证明、Run 归属验证与恢复优先级 |
| `views/ChatView.spec.ts` | URL/刷新/归属/历史选择/successor/Mission 恢复测试，原 fixture 补齐真实 missionId |
| `views/MissionWorkspaceView.vue` | 仅替换两处 Run 状态集合引用；未改导航和同路径切换逻辑 |
| `composables/useWorkflowProgress.ts` | 以 Run status 决定终态，保持原轮询实现 |
| `composables/useWorkflowProgress.spec.ts` | 补测所有终态及 status/phase 不一致的行为 |
| `composables/useChatWorkflowPresentation.ts` | 补齐 succeeded 和 superseded 文案 |
| `components/agentos/WorkflowRunPanel.vue` | 补齐同两种已有后端状态文案 |
| `services/api/agentos/types/workflow.ts` | 前端类型补齐已有 succeeded/superseded 状态 |

另新增本报告。未改 Conversation/Chat 后端接口、数据库、Schema、Dispatch、C2、ACG Copilot、启动内核或页面模板/CSS。

## 4. 身份合同

| 身份 | 本轮处理方式 |
|---|---|
| `Conversation.id` | 数据库 UUID，仅元数据；不作为模型历史键或 URL contextId |
| `contextId` | 原聊天历史定位键，原值用于历史 GET、续聊和 URL |
| `chatContextId` / `chatRoleId` | Mission 创建时冻结的输入快照，迁移不回写 |
| `binding.conversationId` | 本地关联主键，可由有证据的 draft 迁往真实 contextId |
| `conversationAliases` | 在现有 binding/reference 内保留历史键；不是新 Session 状态或后端字段 |
| `missionId` | 正式任务身份；必须与读取到的 Run 归属一致 |
| `runId` | 执行实例身份，同时是本地去重键；不代表 Mission 的最新 Run |
| `operationId` / `clientRequestId` | 原启动身份，保留原值及原 LaunchAttempt 存储位置 |

一个 context 的 binding 数组可保留多个 Mission；同一 Mission 可保留多个不同 Run。迁移不会按 Mission 去重。

## 5. Conversation 恢复机制

- `loadHistory(contextId)` 是历史恢复入口，设置本次目标和请求代次，同时读取原消息及现有 `conversationApi.getConversation(contextId)` 元数据。
- 元数据 contextId 必须等于本次目标才恢复 roleId；允许原 roleId 为空。开始恢复时清除上一会话角色，避免跨会话残留。
- 消息、角色、使用量和 loading 的回写均受到请求代次和目标 contextId 保护。切换 B 或清空草稿后，A 的成功/失败/finally 均失效。
- `setContextId(non-null)` 返回 `loadHistory` 的 Promise；null 只清空并使旧请求失效。View 发现目标 context 已在 Store 中时不会再加载一次。
- 历史元数据失败或 contextId 不匹配时，可保留读取到的消息，但记录恢复错误并阻止普通发送，避免带错误角色/模式续聊。恢复请求可通过原 loadHistory 入口重试。
- 传输 workspaceMode 取原 Conversation 元数据，兼容旧索引和 Agent binding。普通及文件/流式发送都尊重已恢复模式；没有将旧 Agent Conversation 强制改为 chat。
- 首次发送取得 contextId 后增量 `router.replace`，保留所有已有 query；不重新加载刚收到的消息。空 context/draft 不发起历史读取，也不自动创建 Conversation。
- 全新空白页面仍可生成本地 draft 键；它不作为新的 LaunchAttempt/clientRequestId。历史恢复页面不生成这一草稿 UUID。

## 6. draft 迁移机制

- 只在当前组件开始首次聊天/文件发送前记录当前 draft；接到 contextId 时，必须仍是无历史 URL 的同一 draft、此前没有 contextId，且不是历史加载过程，才调用迁移。
- 仅本地 binding/reference 索引改变。真实 context 下已有记录与 draft 记录按 runId 合并；保留 draft 别名，删除冗余 draft bucket。
- 如同一 runId 在两侧指向不同 Mission，拒绝整次归并并保留原索引。未知 draft、不匹配的目标 context、历史页面加载不会猜测迁移。
- reference 仍以原 runId 为键，只更新已有记录。已存在于真实 context 的相同 reference 也补充历史别名；不重新 register 或创建 reference。
- binding 的状态更新/失效标记支持旧别名，刷新后可从同一 v1 存储读回别名。
- 不插入消息、不移动或编辑 LaunchAttempt、不重写 operation/client ID、冻结请求或原始 input。测试以真实 `createMissionLaunchAttempt.begin` 建立快照，比较迁移前后的整个 sessionStorage 和完整 pending identity。

## 7. Run 恢复与终态规则

恢复顺序：URL 显式 Run（及指定 Mission）→本会话已验证选择→最近有效的后端确认非终态 binding→已读取验证的历史 Run→空状态。

- 显式 runId 不因绑定中的最新 Run 或 `supersededByRunId` 改变；不会跟随 successor 自动跳转。
- URL 仅指定 missionId 时读取既有 Mission workspace 投影，读取其现有 Run，再验证 Run 的 missionId；将有效选择写入 URL，保留其他参数。
- 后端返回 runId 必须匹配请求 runId；存在预期 Mission 时，还必须匹配 missionId。URL 或 binding 的归属不一致时不选择替代 Run、不伪造 binding。
- 本地历史 binding 只提供候选，不视为最新 Run 事实；候选由 GET Run 验证。最新候选与当前选中实例分别处理。
- 预读取的已验证 Run 只传递一次给原详情加载器，避免恢复时重复 GET；原详情重试和缓存机制保留。
- 显式历史 ID 暂时不可读取时，保留 URL 和原有详情失败/重试展示，不认定其为有效 binding；后续详情成功仍须验证归属。恢复过程中不创建 Mission/Run。
- 活动状态：pending、planning、running、waiting_review、retrying。
- 终态：failed、completed、succeeded、cancelled、superseded。completed/succeeded 展示成功，superseded 展示被替代。
- status 独立于 lifecyclePhase 和 Formal Control；例如 retrying 即使出现旧 failed phase，仍继续轮询。未改变 Runtime 状态机。

## 8. 验证记录

新增 36 项行为测试（新增两个 spec 并扩展既有 spec）。未删除或放宽旧断言。

| 验证 | 结果 |
|---|---|
| 修改前复现：`npm test -- src/stores/chat.session.spec.ts` | 2 条失败，证实角色残留与 A/B 竞态 |
| 首轮定向回归 | 7 文件、69 测试通过 |
| 扩展后的定向复核 | 5 文件、94 测试通过，包含原 MissionWorkspaceView 31 项测试 |
| 初轮完整回归 | 129 文件通过、2 文件失败；921 测试通过、2 失败，另有 1 未处理计时器错误。保留失败证据，不作为最终通过结果 |
| 冻结源码后完整回归：`npm test -- --maxWorkers=2 --minWorkers=1` | **131 文件、923 测试通过，退出码 0，无未处理错误；161.97s** |
| 独立 TypeScript：`npx vue-tsc -p tsconfig.json --noEmit` | 退出码 0 |
| `npm run build:web`（再次包含 TypeScript） | 退出码 0；Vite built in 30.02s |
| `git diff --check` | 退出码 0；仅原有 LF/CRLF 提示 |

补充检查：全部新增文件无行尾空白；ChatView 和 MissionWorkspaceView 的 template/style 块与 HEAD 完全一致。最终 diff 已逐项审查；未暂存修改，结束 HEAD 仍为 `081aa3fd22903d3b73c98d1a25dc750b3f036557`。

初轮全量执行期间源码仍有修订，新增冲突保护断言与已转换模块交错；同时原 Workbench runtime 流测试失败，并在测试环境退出后触发 localStorage 计时器错误。随后冻结源码，以 `--maxWorkers=2 --minWorkers=1` 降低调度负载复核；旧 Workbench 测试不变，定向 31 项已通过。最终完整回归仍执行全部 spec，不屏蔽失败或异常。

无副作用证据：历史恢复测试监视两套 HTTP client 的 POST 及 UUID 生成，均未调用；迁移测试监视任务创建和 Material 创建，均未调用，并断言消息数/reference 数不增加、整个 LaunchAttempt 存储字节串及 identity 不变。View 刷新不调用启动、发送或迁移；错误归属不轮询、不读取拓扑、不创建 binding。完整回归还覆盖原 Launch Safety、幂等、恢复、策略及架构约束测试。

本机日志保留于 `%TEMP%`：`pr-ui-02a-red.log`、`pr-ui-02a-focused.log`、`pr-ui-02a-focused2.log`、`pr-ui-02a-focused-final.log`、`pr-ui-02a-full.log`、`pr-ui-02a-full-final.log`、`pr-ui-02a-type.log`、`pr-ui-02a-build.log`。受保护文件基线为 `pr-ui-02a-protected.json`。

## 9. 兼容性与尚未实施事项

- 原 v1 binding/reference 存储仍可读取；缺少别名字段的旧记录无需全局迁移。迁移仅发生在有当前发送证据的本地索引上。
- 旧 Agent workspaceMode 保留；旧 contextId 未替换成数据库 UUID。
- 未验证真实浏览器到真实后端的端到端往返；当前证据为 Vitest/jsdom 行为测试、源码合同检查、类型检查和实际构建。
- 无可靠关联证据的历史 draft 继续保留；不尝试从冻结 LaunchAttempt 推测或重写历史会话。
- Shell 模式切换/clearMessages 边界、Workbench 同路径 Run 切换、双视图导航仍留给 PR-UI-02B。
- 本轮不提供新的元数据恢复错误 UI 或多任务管理 UI；沿用现有错误提示和历史读取入口。

## 10. 关键源码位置

| 文件与行号 | 内容 |
|---|---|
| `features/workspace/session.ts:2` | 共享 Run 状态 |
| `features/workspace/session.ts:19` | 会话别名匹配与 binding 查找 |
| `features/workspace/session.ts:27` | draft 合并及冲突保护 |
| `features/workspace/session.ts:47` | Run/Mission 验证 |
| `features/workspace/session.ts:51` | 恢复优先级纯函数 |
| `stores/chat.ts:256` | 本地关联迁移 |
| `stores/chat.ts:805` | 历史代次及元数据恢复 |
| `stores/chat.ts:890` | setContextId 调用合同 |
| `stores/workflowRuns.ts:222` | reference 原位迁移 |
| `views/ChatView.vue:1298` | 详情重试时再次验证归属 |
| `views/ChatView.vue:2104` | Run 恢复入口 |
| `views/ChatView.vue:2198` | 当前发送证明及 URL 同步 |
| `composables/useWorkflowProgress.ts:73` | 只按 Run status 判断终态 |
| `views/MissionWorkspaceView.vue:362` | Workbench 复用同一终态判断 |

最终状态：**SELF-TESTED**；不提交、不推送、不部署，修改保留等待独立验收。
