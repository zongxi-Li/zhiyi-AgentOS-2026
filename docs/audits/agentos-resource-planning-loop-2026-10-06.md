# Resource Plane 与 Runtime Planning Loop 接线报告

日期：2026-10-06。实现基于本地 master `8e4f6035715c8cef9462871225b12ddc75079187`，本轮不创建提交，不修改前端或用户任务数据。

## 缺失的控制环

资源器已负责执行资源过滤、评分、租约、模型端点匹配及远程换绑，但 Planner 原先主要看到节点健康状态。节点在线并不证明当前步骤的能力、信任、部署位置、模型需求和容量得到满足。Scheduler 异常进入 Recovery 时还会丢失 `NO_MODEL_ENDPOINT` 等具体原因，无法据此形成可靠等待。

本轮复用 ResourceBinder、现有 Planning Loop、Recovery、Checkpoint 和运行期唤醒扫描，没有增加第二套调度或恢复系统。

## 实际运行链路

1. 执行以已持久化的 `ExecutionRequirement` 为资格约束。Binder 按现有硬约束、评分、模型候选及租约 authority 分配资源。
2. 短期容量等待和有界远程换绑继续自动推进。换绑重试使用新的 Attempt/commit 身份；已提交结果不重执行。
3. 调度最终失败时保留结构化原因、步骤和候选排除原因，交给现有 Failure/Recovery 与 Planner 边界。
4. Planner observation 加入最多 16 个未完成步骤的资源事实，优先失败步骤；每步最多 16 个候选。内容包含需求摘要、需求指纹、就绪判定、快照版本、匹配模型端点版本和最近换绑记录，不导出原始资源 metadata、凭据或策略 metadata。
5. Planner 可提出 `requirement_available` 等待，指定步骤、冻结需求指纹和截止时间。确定性应用层拒绝完成步骤、错误指纹、已就绪目标、过期或超过 24 小时的截止时间。
6. 现有唤醒扫描读取 Binder 的需求就绪判定。扫描不获取租约、不调用模型；本地嵌入式执行资源由当前进程刷新其自身存活信号。单纯节点在线或出现不兼容模型端点不唤醒。
7. 就绪或到期形成带 outcome 的持久化 wake，附资源版本证据，由 Planner 基于当前状态重新决策。到期只返回决策权，不自行重试或宣告成功。
8. Planner 的 recover 仍经过现有 Recovery authority。资源故障恢复落实前重新检查冻结需求和当前就绪状态；资源在观察后消失时拒绝执行该决定。最终绑定仍需原子的容量租约，唤醒证据不能替代授权或预留资源。

## 职责及恢复一致性

Planner 决定等待、恢复、修改计划、询问或结束；不能自行选择资源、改变硬约束、提交输出。Scheduler/Binder 保留资格、评分和租约权威，Recovery 保留重试及恢复状态转换权威，Auditor/Artifact 验证继续提供任务事实，Semantic Revision 保留计划修改校验。

远程换绑的内部递归不重复进入 Planner 的 resume 边界；换绑耗尽才返回失败边界。普通进程恢复仍经过 resume。等待、wake、需求指纹和 planning round 随现有 Run/Checkpoint 存储；重启后可继续等待，已写入的 wake 可重新投递，已决定的旧 round 可恢复。新增空字段保留旧 observation 指纹语义，并兼容旧失败决定的重放。

## 验证

新增 16 项测试：Binder 3 项，资源规划与持久化 Runtime 路径 13 项。覆盖无租约观察、真实租约容量、零快照容量、协调器不可用、缺模型等待、不匹配模型不唤醒、需求变化、截止时间、非法等待、重启与重复投递、唤醒后及决策期间资源消失、已提交上游复用、远程换绑成功和耗尽、旧失败 round 重放。

| 范围 | 结果 |
| --- | --- |
| AgentOS 全量 | 940 passed，2 failed，179.77 秒 |
| 受影响 Agent 应用层/API/协调器/组装及本地 Runtime | 68 passed，21.45 秒 |
| 修改文件 Ruff 与 HEAD 对比 | 基线及当前均 30 个存量问题，新增 0 个 |
| git diff --check | 通过 |

两项全量失败为此前已确认的基线问题：`test_v2_schema_is_independent_and_complete` 的 schema 版本期望不一致；`test_run_snapshot_outbox_excludes_execution_bodies` 的旧 fixture 未产生预期 outbox 记录。本轮未修改这两条机制或通过删测试规避失败。

测试日志位于 `output/agentos-runtime-loop/resource-planning-20261006/final.txt` 和 `app.txt`。测试使用隔离数据库，未调用真实模型或启动外部执行后端；前端未改动，浏览器验收按用户要求留给人工。

## 能力边界与下一步

需求等待已经真实接入已有 Loop，但不是自动健康探测或默认模型迁移：只有冻结 `ExecutionRequirement.model` 声明了 `ModelDemand` 的步骤，才按模型端点需求判定就绪。现有 BindingManifest 默认生产路径仍不生成该字段，旧角色/default-model 兼容选择路径继续存在；本轮没有凭空推断上下文长度、工具或 JSON 能力需求。下一步最值得做的是把真实执行能力的模型需求声明贯穿编译和冻结边界，并设计已有 compiled package 的版本兼容，逐步收敛默认模型回退路径。

资源就绪是带版本的观察提示，不是全局原子快照、端点网络可达性证明或模型真实能力验证。Recovery 落实和执行绑定各自重新校验；真实远程 backend、模型配置变更和最终业务产物仍需要现场验收。

人工验收重点：对有明确模型需求的失败步骤补入兼容端点，观察一次条件唤醒和新的 Planner 决定；在等待期间重启服务，确认等待继续且上游不重复执行；只补入不兼容端点不应恢复；资源在恢复前撤销应被拒绝；等待到期应交回 Planner，而不是盲目重跑。现有原样重跑、断点 replacement Run、用户回答和审计暂停继续走原 authority，本轮全量回归通过其既有测试，不据此宣称新的真实业务任务已完成验收。

## 后续修复：服务启动与资源中心适配

旧版本持久化的本机 Node 没有 bootstrap 管理标记，导致新版 `ensure_node` 拒绝登记，Python 服务无法启动。增加了严格兼容路径：仅允许字段一致、无元数据、无归属、无节点凭据的 HOST_TRUSTED Device 旧记录补齐标记，不接管外部身份，也不重置快照。资源组件 74 项测试通过，增加重启保存及凭据/信任/归属/管理标记冲突的回归。实际容器已恢复健康，任务数据未清空。

用户随后授权前端适配。资源中心原先只按 local/terminal/edge/cloud 分组，后端的新 device 值导致有资源却不显示；注册表单仍提交旧 ResourceProfile，缺少 runtimeId/nodeId/ownerScope。

- 概览统一旧位置与 device，保留未知位置行，增加独立承载节点目录；节点目录失败不遮蔽服务目录。算力按节点去重，默认零值不当作已登记算力，健康明确显示未知数量。
- Java 目录白名单增加 runtimeKind、宿主节点、信任、显示名称及有限模型描述字段；新增 typed Node 查询及节点注册转发，继续沿现有 Gateway 和 Python ResourcePlane。目录不导出原始 metadata 或凭据引用。
- 注册只区分 Node、execution_backend、model_server、tool_service；远程 Runtime 选择已有节点并继承放置、信任和归属。节点注册初始 offline，Runtime 初始 unknown；凭据仅注册成功时显示，用户确认保存后关闭。模型端点仍由模型配置同步，不把 ModelServer 登记宣称为 ModelEndpoint 登记。
- 详情区分执行服务与模型端点；端点不请求 Runtime 使用/凭据/探测接口，不显示 Runtime 启停开关或伪装执行槽位。
- 资源/节点查询使用 15 秒超时，替代普通 Run API 的 240 秒等待；保留取消与旧请求隔离。删除不再使用的旧注册画像/快照类型、隐私/部署表单字段及相关样式、无用 filteredCount。注册组件与类型文件净减少约 170 行。

验证：受影响 Python API 48 项通过；前端全量在当时工作区为 609 passed/1 timeout（610 项），超时的 App 用例及资源中心最终相关用例一起重跑为 18 passed。Java 定向及边界检查 54 passed/2 failed，失败涉及 HEAD 已存在的 Copilot Map/Object 响应和未纳入严格投影的资源凭据 GET；未修改这些返回类型或放宽检查。Node/Artifact 控制器、资源 Mapper 的 18 项及一般架构 30 项均通过。

实际 `9050 → Java → Python` 只读请求：资源和节点目录均 200、各 1 条，返回 runtimeKind/nodeId/trust 等新字段。Java 已通过现有开发容器重启编译；五个服务均健康。未注册真实测试资源、调用模型、创建任务或做浏览器自动验收。

普通宿主 Web 构建先遇到 esbuild 临时文件删除拒绝，再遇到共享 components.d.ts 写入冲突；采用隔离的当前源码副本和临时目录验证，避免与正在运行的 Vite 生成器争用。构建最终结果及日志见 `frontend-build-isolated.txt`。所有日志仍集中在原忽略目录。本轮没有提交；其他会话的 BrandLoader、页面加载及知识图谱改动保持原样，不归入本轮归属或验收结论。

人工验收：刷新资源中心，确认本机节点、执行后端和“未登记”算力可见；打开详情核对宿主身份与未知状态；打开注册弹窗查看四类对象，已有远程节点可用于 Runtime 登记；确有接入需求时再注册，并保存一次性凭据、提交真实签名心跳。模型端点详情需已有端点配置，不能通过注册执行后端伪造端点能力。

## 后续修复：任务级 Copilot 与重跑环境边界

现场 Run `run_650fe515656f` 是 Copilot 从已完成 Run `run_2f7f44e7eceb` 创建的全量重跑，不是模型节点执行失败。它复制了源 Run 的过期 capability catalog revision，准备阶段未校验，执行前才被 `PLUGIN_SNAPSHOT_CHANGED` 拒绝。日志同时暴露 Mission `completed -> failed` 的非法迁移。

全量重跑保留输入、TaskPlan、Blueprint 和 bindings，但不复用旧结果；在预览时验证原计划所需能力和 Agent 仍可用，冻结当前安装环境的完整 scope 指纹。确认时重新校验指纹，环境变化必须刷新方案。新 Run 使用现有语义、绑定、编译及 Scheduler 校验流程。旧输入和原 Run 不修改；界面明确提示执行环境是否更新。部分重跑和恢复涉及已提交结果，继续要求原冻结快照成立，冲突在预览或准备时拒绝，不再发布一个必然执行失败的继任 Run。显式 scope override 也统一在 Run 分配前验证。Mission 的失败投影只允许归属正确的当前 Run 更新，旧成功 Run 的终态保持不变。

权限现在独立存储于 `task_copilot_permissions`，以 Mission 为键，不放进易被节点结果覆盖的 Run 快照。用户通过权限选择明确修改该任务策略；消息、回答、预览和确认均校验服务端策略。只读消息仍可使用，模型没有修改策略的工具。沿用既有 owner/tenant 访问检查，外部任务的权限修改返回 404。任务删除时清理策略，新 Run 和服务重启不会重置用户选择。

对话按 Mission 汇集最近 30 条，并保留每条 sourceRunId；给模型的历史仍仅最近 4 条，当前事实来自新鲜 Runtime observation。前端历史 Run 不再禁用任务助手，提供前往当前运行的入口；旧方案确认始终使用其来源 Run 和 revision，回执与消息键同时包含 Run 身份，避免跨运行误匹配。当前运行查询保留 owner/tenant 过滤。任务级协作不是无约束执行权限：Planner 仍决定战略动作，操作需确认，Recovery、Semantic Revision、Auditor 和 Scheduler 权威不变。

验证：最终 AgentOS 全量 949 passed / 2 failed（951 项，174.18 秒），两项为前文记录的 schema 版本和旧 outbox fixture 基线问题；相关准备、恢复和审核 31 项通过；受影响 API 49 项、前端 Copilot/工作区 46 项、Java Review 控制器 7 项通过。类型检查和隔离 Web 构建通过（19.09 秒）。全量日志为 `task-copilot-agentos-final.txt`，构建日志为 `task-copilot-web-build.txt`。最后补充了模型提示中的 Mission/当前 Run 身份说明，另跑相关 API 验证。

部署与现场只读检查：现有开发容器已加载代码，五个服务健康；从原 Run 和失败 Run 查询 Copilot 均返回同一 Mission、同一当前 Run、任务权限及带来源的共享对话。未调用真实模型或替用户创建新的重跑，原失败记录保留。人工验收：刷新页面，重新生成全量重跑方案并确认（不要复用旧方案）；检查进入首节点与后续 Loop；在同任务不同 Run 切换权限，确认选择和对话延续；查看历史 Run 时通过入口前往当前 Run。当前代码及其他会话新增的改动均未被本轮提交或覆盖。
