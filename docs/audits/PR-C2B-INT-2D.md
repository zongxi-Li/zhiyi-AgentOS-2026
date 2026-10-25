# INT-2D 正式 Workbench 生命周期接线

日期：2026-10-25。阶段结果 **SELF-TESTED（受限，等待独立复验）**；不得视为生产验收。

## 入场与范围

GitHub / 本地入场为 `250a04c93c8734f355f252938a7fecd2812752a7`。先复现 INT-2C P1：Permit-only 直接 Runtime 执行实际调用 A/B/C 并提交三个 NodeExecution。共享 Native 认领边界修复、133 项 API、165 项核心恢复及 109 项门禁装配测试通过后，固化为 `cc35fa291990148825116935594cd793c2eac4c8`，详情见 `PR-C2B-INT-2C-CLOSEOUT.md`；之后才实施本阶段。

保留用户此前删除的文档；未改前端路由体系、compose、生产配置或开关；未升级真实业务库。新增只读字段不产生权威事实，没有第二个 Workbench、Runtime、Scheduler、许可或恢复状态机。

## 实际接线矩阵

| 用户动作 / 观察 | 现有前端入口 | 正式 HTTP / 服务端边界 |
| --- | --- | --- |
| 创建任务与正式规划接受 | CreateMissionView / startWorkflowAsync / 已有 creationRetry | POST `/missions`；语义输入与既有 Planning 接受流程；不自动 Dispatch |
| 准备图 | 右侧 FormalExecutionControls | POST `/missions/{mission}/runs/{run}/graph/materializations`；原 Materialization Authority |
| 激活并保持暂停 | 同一控制区，单次明确操作 | POST 同前缀 `/graph/activation`；原 Activation Authority，`ACTIVATED_PAUSED` |
| Handoff | 同一控制区 | POST `/graph/handoffs`；原 Handoff Authority，`STATE_PREPARED` |
| 签发许可 | 同一控制区 | POST `/graph/permits`；原 Permit Authority，`ISSUED`；没有跟随 Dispatch |
| 明确执行 | 独立“执行任务”按钮 | POST `/execution/dispatches`；原 Coordinator.submit_permitted → Native Scheduler → 本次收束后的认领校验 |
| 状态 / 重开任务 | 原 RuntimeObservationAdapter + RunRuntimeStore | GET `/runs/{run}`、原 SSE / 轮询；观察快照携带已查询的 Run，不另建轮询或状态存储 |
| 审核 | 复用 WorkflowReviewPanel / useWorkflowReview | 原 POST `/runs/{run}/reviews`；稳定 operationId 与冲突处理不变 |
| 取消 | 原 MissionWorkspaceView.cancelActiveRun | 原 POST `/runs/{run}/cancel`；保留确认与受控取消 |
| Artifact | 原左侧引用与 ArtifactEditor | 原 Run-scoped manifest 查询 / 下载；不把临时字符串补成最终交付 |

真实 Java 网关原来没有转发上述五个控制路由，且 RunProjectionMapper 会丢弃 formalControl。本次在现有 Mission Controller 补传输转发，复用原 AgentOsClient、HTTP 状态处理及 TrustedUserContextForwarder。后者从 Spring Security 构造身份，未从浏览器读取 principal / 内部身份头。Python 原请求 schema 继续 `extra=forbid`，唯一 Authority 继续决定权限、比较条件、幂等与执行。

GET Run 增加 `dispatchEnabled` 和 `dispatch` 公共事实发现；已关闭模式也能读取历史命令。读取在原 Workflow 快照中校验 schema、记录 checksum、Mission/Run/Permit/Graph 与 revision 关联，损坏返回 503；不对账、不启动 Task。回执仅 `dispatchId/runId/permitId/graphVersion/status`。Java 使用 FormalControlQuery 显式投影并过滤内部字段，故障仅保留 code。Dispatch 开启时 `executionAuthorized` 还要求持久命令，`dispatchEligible` 仍指可申请命令，二者不能混为实际执行中。

## 交互与权威状态

沿用全局 `--wb-*`、原字体、细边框、小按钮及左导航 / 中央编辑器 / 右检查区 / 底部事件布局。控制区作为右栏一个紧凑区域，审核也复用既有组件；图、许可与业务状态分别展示。

动作从服务端 Run 与 formalControl 引用派生，未知状态、缺少引用、历史 Run、读取失败和授权 / 版本拒绝禁用危险操作。实际 HTTP 联调确认 Run 在 Planning Accepted 乃至 Permit ISSUED 时仍可为 `planning`；前端因此支持该真实合同，不擅自改成 pending。进度文档执行前显示原始正式阶段 / Permit ISSUED / Dispatch ACCEPTED，只有实际运行才显示 RUNNING。

每个动作的本地 retry hint 按 Mission/Run/动作/持久源引用隔离，先持久保存 operationId 再发请求，Dispatch 保存首次 expectedRuntimeRevision；重复点击有同步 pending guard。刷新或 ACK 丢失后复用原 key 和版本，不把本地缓存当权威状态。只缓存 operationId、source 和比较 revision，再从已查询事实按白名单构造请求，不能从缓存注入 principal、Permit、Command Record 或执行状态。缓存不可用 / 损坏时阻断。组件销毁忽略迟到响应。202 后只请求刷新，不乐观标记运行 / 完成，不自动继续下一控制步骤。

示例（IDs 为真实引用的缩写）：

```http
POST /api/agentos/v2/missions/{mission}/runs/{run}/execution/dispatches
Authorization: Bearer <user-session>
Content-Type: application/json

{"operationId":"wb-6e819494-1d12-4358-8b9e-afc8e97eb3f8","expectedPermitId":"xpermit_...","expectedGraphId":"initial_...","expectedGraphVersion":1,"expectedRuntimeRevision":2}
```

```json
{"operationId":"wb-6e819494-1d12-4358-8b9e-afc8e97eb3f8","dispatchId":"dispatch_...","runId":"run_...","permitId":"xpermit_...","graphVersion":1,"status":"ACCEPTED","runStatus":"planning","errorCode":null}
```

该响应是命令接受回执；后续 GET Run 的 `status=completed` 和正式 Artifact 引用才是完成观察依据。

## 验证与真实浏览器边界

INT-2D 定向命令（根目录）：

```powershell
python -m pytest apps/agent/tests/test_agentos_c2_dispatch_projection.py apps/agent/tests/test_agentos_c2_dispatch_admission.py apps/agent/tests/test_agentos_c2_dispatch_http.py apps/agent/tests/test_agentos_c2_http.py apps/agent/tests/test_agentos_c2_permit_http.py -q --disable-warnings --maxfail=1
```

新增 Projection 两项先行通过：2 passed, 2 warnings in 34.88s，退出码 0；覆盖查询不写入、重建服务 / 关闭模式发现历史回执、损坏记录拒绝及零执行。

最终完整 HTTP 子集：**59 passed, 3 warnings in 204.40s，退出码 0**。运行使用 Python subprocess 直接写入日志并单独落盘退出码；中断前未归档的子进程结果不计入通过证据。

Java（cwd=`apps/backend`）：

```powershell
mvn -q -Dtest=AgentOsMissionControllerTest,AgentOsRunControllerTest,AgentOsRouteCompatibilityTest,AgentOsGatewayServiceTest,QueryProjectionArchitectureTest test
```

34 项，failures=0 / errors=0，退出码 0（Surefire XML：12+6+3+6+7）。验证五个实际转发路径、202 不变、公共投影字段保留 / 私密字段剔除、畸形字段 502、原路由和投影架构。没有放宽架构测试。

前端（cwd=`apps/frontend`）：

```powershell
npm exec vitest -- run src/components/workspace/FormalExecutionControls.spec.ts src/components/workspace/RunProgressEditor.spec.ts src/views/MissionWorkspaceView.spec.ts src/views/CreateMissionView.spec.ts src/workbench/runtime/observation.spec.ts src/workbench/runtime/runtimeEvents.spec.ts src/components/agentos/WorkflowReviewPanel.spec.ts src/composables/useWorkflowReview.spec.ts src/components/workspace/ArtifactEditor.spec.ts src/services/api/agentos.spec.ts src/services/api/agentos/api/c2.spec.ts --maxWorkers=2 --minWorkers=1
npm run build:web
npm run build:desktop
```

前一轮完整前端 150 passed / 11 files / 59.96s，退出码 0；最后源码再次执行：**150 passed / 11 files / 80.33s，退出码 0**。包括稳定 Dispatch、ACK 丢失后重挂恢复、重开读取、403/409/422、缓存损坏、未知 / Legacy、审核 / 取消、Artifact 下载、真实阶段标签。首轮新增测试曾按旧按钮文字查找“提交中”按钮而失败，修正稳定选择器后通过，没有降低断言。已有 jsdom 用例包含网络 fallback 的连接拒绝诊断，不能表述为无控制台错误。

Web / desktop 均执行 vue-tsc 后构建通过，初次分别 33.79s / 24.70s，退出码 0。最后源码关闭预览后串行复跑：**Web 18.43s / desktop 12.60s，WEB_EXIT=0 / DESKTOP_EXIT=0**。期间一次与开发服务器同时写 components.d.ts 遇到 Windows `UNKNOWN open`，退出码 1；关闭开发服务器后原命令通过，无实现 / 测试断言变更。最终 dist 搜索不包含临时预览入口或测试 bearer 字符串。

真实 Chrome 在现有 MissionWorkspaceView 上逐步点击五个正式动作，HTTP 接入生产 Runtime 装配、临时 SQLite、真实 Authority、确定性 ContractReviewAgent 和正式 Native Scheduler。创建 Mission 由测试 HTTP 预置，不声称浏览器创建页与真实 Provider 已完成全链验收。测试桥只注入本地测试身份，未跑 Java 登录链；Java 转发 / 身份路径另有定向测试。桥不转发 SSE，浏览器走原正式 Run 轮询，控制台因此有预期 SSE 503，Identity 尚未准备时有 execution-tree 404。不能冒充完整生产 SSE / IAM E2E。

第一轮实测 `run_65869defcde3`：Permit 后与页面刷新后 nodeCalls=0 / dispatchPosts=0；双击执行只一个 Dispatch，A/B/C 各一次，Run=completed，原生 checkpoint / 审计 / manifest 由 HTTP 回归交叉验证。会话中断后预览服务关闭，随后重新构造临时服务复验最后源码。

最后源码重新装配实测 `mission_12ee3bc5ba46` / `run_338f98b76eb1`：逐次点击物化、激活、交接、许可；Permit 后和重载后仍零节点调用 / 零 Dispatch。双击执行提交单个 `operationId=wb-...`，HTTP 202 后通过正式查询观察 completed；A/B/C 各一次，activeSlots=0；再次刷新仍单一 Dispatch / 三次调用，读取原 ACCEPTED 回执。正式 manifest `manifest_4163fb3453804aa1bef84a80827df00c`：sealed=true，833 bytes，SHA256 `43d1d647d4f3c670374f15053d98f98b46a584aec8cbdc0361c011cfed65dd4f`，producer C / `semanticTaskKey=step:C`，角色 supporting_artifact。浏览器点击原 ArtifactEditor，正文可见，点击下载的真实 Run-scoped GET 返回 200。没有调用 Vue 私有 setupState 驱动验收。1440×900 检查保留编辑器四区域、控制按钮和长引用无溢出。

预览已关闭：确认节点完成、无活动 slot 后，关闭 Vite；HTTP 桥的 Windows 重定向父进程退出后子进程仍持有端口，核实命令行为本次测试脚本后定点终止，18952 / 18953 均无监听。该桥不是生产宿主，不能把强制终止表述为生产优雅关闭；原 Coordinator / Runtime teardown 的真实集成回归另有验证。临时 HTML/TS 入口已移除。

## 已知限制与独立验收入口

- P0/P1：自审与关键红绿反例未发现遗留执行绕过；Native guard、既有 Coordinator 与持久 Command 一致，无新增 P0/P1。
- P2：生产 IAM + Java + Python + 真实 Provider + SSE 全链尚未验收；仅本地认证桥浏览器联调与各层真实合同 / 转发定向测试。生产开关保持关闭，Schema 升级必须显式运维操作。
- P2：确定性业务示例产生真实 supporting Artifact，但未提供正式 final-deliverable 引用。页面如实显示 Final deliverable missing，可读取 / 下载已登记 manifest；不把 completed 自动等同最终交付已齐备。真实业务最终交付仍需其既有正式引用与业务验收。
- P2：继续沿用单 Runtime、受控恢复和未知外部副作用阻断；不宣称跨库原子性或远端 exactly-once。
- P3：retry hints 是浏览器提示，可由浏览器清理；服务端 Dispatch ledger 才是权威。清理后若已接受，通过查询发现；若未接受，将由现有服务器并发 / 幂等合同拒绝冲突。

INT-2E 入场前应独立复验本次 Native 必要条件和前端真实生命周期，补生产 IAM / SSE / Provider 及正式 final-deliverable 场景。当前任务完成后停止，不自动进入下一阶段。

## 最终归档

实现提交：`00a96678853f4c422964a6da48ed15df032956e2`（21 个源码 / 回归 / 生成声明文件）；INT-2C 独立收束提交：`cc35fa291990148825116935594cd793c2eac4c8`。本报告单独提交，报告自身最终 SHA 用 `git log -1 --format=%H -- docs/audits/PR-C2B-INT-2D.md` 定位，避免 SHA 自引用。完整修改文件可用 `git show --stat 00a96678` 及 `git show --stat cc35fa29` 审阅。

门禁已全部通过，`git diff --check` 与 `git diff --cached --check` 均退出码 0；最终自审关注共享 Native 认领、只读完整性、网关身份来源、没有 watch 自动派发、重复点击 / ACK / 版本重试、未知状态禁用及 Artifact 来源，没有遗留已证实 P0/P1。

推送前实时 `git ls-remote https://github.com/zongxi-Li/zhiyi-AgentOS-2026.git refs/heads/master` 为入场 `250a04c93c8734f355f252938a7fecd2812752a7`；必须确认其为本地 HEAD 祖先后，仅向该显式 GitHub URL 推送 `HEAD:refs/heads/master`，不用同时带 Gitee push URL 的 mirror。最终报告提交与远程相同 SHA 的推后核验记录在交付回执；未授权强推或隐式合并。

临时预览入口、日志、数据库、缓存与测试凭据不提交；未推送 Gitee，不部署，不开启生产开关，不运行无关全量测试，不清空冻结门禁历史耗时缓存。完成本阶段后停止。

构建前后九个关键源码 SHA256 完全一致（工作区原始字节）。入场列为 `git show cc35fa29:<path>` 的原始 Git blob；新文件以 NEW 标识。换行差异与逻辑变更通过 Git diff 同时核验。

| 文件 | 入场 SHA256 | 最后源码 SHA256 |
| --- | --- | --- |
| `apps/agent/app/api/agentos_c2.py` | `c032cbd2ea12e84550f665341ab60df3c324060b3905d12fff75879f65d99282` | `5e04d1522d2cdc7306f14484845b3a6ebe5c03b88b5f4f8ce83e9b6e270f2d1e` |
| `apps/backend/src/main/java/com/kinlin/ai/controller/AgentOsMissionController.java` | `ec7582eb1be67575accca55b69a664eb27eee0d507087767cd7aef9237b2be60` | `f1d78ae9f1bb0e9a40a8ea05de854c144bfe5200029433b3de07acac68e5e425` |
| `apps/backend/src/main/java/com/kinlin/ai/projection/run/mapper/RunProjectionMapper.java` | `eadd2986e0bb2f02da4e9622694c2e9014f5525ed9a0bf94828fdf227c83ad81` | `056e5e40bee106d0b2889014173e79691ce9529d2590f39efc549c2843bfccde` |
| `apps/frontend/src/features/acg/formalControl.ts` | `NEW` | `3876f8f8dd01d7ee98b73753ab78716e83491979d9cf19a55e742af4584cde3d` |
| `apps/frontend/src/components/workspace/FormalExecutionControls.vue` | `NEW` | `cbcbe8d3307a98c8487d190a7a70a7340334549c3135da1157a64eebedf2c8c5` |
| `apps/frontend/src/components/workspace/RunProgressEditor.vue` | `f80fac2fd00abc03e486001d070e655745bc551ca2173adab88e9b8a4a96961d` | `7c38ff93a649b95f10a050ee75877dd0bd2a9a73f7fabf1d3bfe791ea4a9d1f0` |
| `apps/frontend/src/views/MissionWorkspaceView.vue` | `310111d7f3db9ab69dcfa42baf37ddddb576d81b04bacc7d21357c75d66cacf1` | `73964e990c6685c603f4e3b6de34d724ccb4adc00e13f4abd471c0b7ee2e850d` |
| `apps/frontend/src/services/api/agentos/api/c2.ts` | `NEW` | `80d815986a95cb78957bbd6a6d1d24f399843c46e0d9f006279fc052377b8530` |
| `apps/frontend/src/workbench/runtime/observation.ts` | `3f2424ff7a08af6b6f5e207c5b311bcbfdfc962310f56228b1b5a16c3c3c8b17` | `126e991b1b8c22e28a4607372479fec14db59926ba3ecbdbcc68a8aea2264f61` |
