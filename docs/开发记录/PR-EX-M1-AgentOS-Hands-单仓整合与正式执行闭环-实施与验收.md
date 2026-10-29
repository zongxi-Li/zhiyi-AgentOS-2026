# PR-EX-M1：AgentOS × Hands 单仓整合与正式执行闭环

日期：2026-10-29；平台：真实 Windows 11。**结论：ACCEPT——本轮正式执行主链与冷重启验收通过。**

最终任务从空测试工作区开始，真实创建 3 个文件，pytest 20 项通过，11 份执行收据校验通过；重启后 Run、内容、文件及收据保持一致。已知未通过项与架构限制见第 9 节，不将其混记为通过。

## 1. 基线与保护范围

- 主仓开工 HEAD：`145726f0a08f9a9ee4acc8255d785c8f10848a5b`；开工工作区干净。
- 原 Hands 仓库：`C:\Users\LZX\Desktop\zhiyi Hands`，HEAD `c48f704b2599102775668739f8838274a2a77068`；未修改、删除、归档或提交该仓库。
- 已阅读 EX-00、Hands 00/01/02 和实际 ResourcePlane、Binder、NodeRunner、AuditedToolRuntime、LocalRuntimeClient、ExecutionPermit、Hands protocol/engine/service/ledger/grants/events/World。
- N03 `default` 不参与本轮任何启停、初始化、恢复或数据写入。本轮独立 Home：`%LOCALAPPDATA%\ZhiyiNative\ex-m1-20261029`。
- default 的 `environment.json`、`credentials.dpapi`、`workspace/n03-persistent.txt` 哈希与开工记录一致。暂停期间部分进程发生外部重启，不能声称其 PID 始终未变；本轮未终止这些进程。
- 未修改 Docker 部署、历史数据库、数据卷、系统服务、ACL、开发者模式或系统权限。未提交或推送 Git。
- 用户正在进行 Tauri → Electron 迁移；本轮复用现有桌面验收，未实施 Electron 接入。此前为并行验收增加的 `kinlin-integration-dev` 只是同一 Tauri library 的独立开发 binary，避免覆盖 default 正在使用的 executable。

证据：[基线保护](../../artifacts/windows/pr-ex-m1/default-before.json)、[保护复核](../../artifacts/windows/pr-ex-m1/default-protection.json)、[导入核验](../../artifacts/windows/pr-ex-m1/import-verification.json)。

## 2. 单仓目录和依赖

`apps/hands/` 导入原仓 138 个 tracked 文件，并追加边界加固与回归。保留独立 package.json、pnpm-lock.yaml、tsconfig、Vitest、service/CLI、历史报告、DSH vendor、MIT LICENSE、PROVENANCE。

未导入 `.git`、node_modules 或原仓临时 evidence。历史报告中的旧证据属于原仓，不能作为本轮通过依据。100 个 vendor 文件逐一 SHA-256 比较未变化。新的安装、构建和服务启动仅引用本主仓路径。

- 安装：`pnpm --dir apps/hands install --frozen-lockfile`
- 类型检查：`pnpm --dir apps/hands typecheck`
- Windows 回归：`pnpm --dir apps/hands exec vitest run --maxWorkers=1 --fileParallelism=false`
- 独立服务：`pnpm --dir apps/hands service --config <受控配置文件>`

来源：[INTEGRATION-PROVENANCE](../../apps/hands/INTEGRATION-PROVENANCE.md)、[原始导入清单](../../artifacts/windows/pr-ex-m1/import-manifest.json)。

## 3. 正式调用链与权威边界

```text
真实桌面 Vue
  → Java JWT / AgentOs Gateway
  → Python Mission / TaskPlan / Planning Commit
  → Graph prepare → activate → handoff → ExecutionPermit → Dispatch
  → Scheduler / CapabilityBindingSolver / NodeRunner
  → AgentOS workspace_developer 的有界工具循环
  → AuditedToolRuntime / GuardedToolRuntime
  → 现有工具审批服务（界面逐次 allow_once / deny）
  → ResourcePlane / Binder / Lease
  → HandsHttpTransport（复用资源 HMAC 凭据）
  → 独立 Node.js HandsService → DSH World → Windows Workspace
  → checksum 校验 / Value Store / Trace / Provenance
  → verification → artifact_generation → AgentOS canonical deliverable
```

Hands 是 `EXECUTION_BACKEND`，不具备 Planner、审核或任务状态权威，也没有 Agent Loop。新的工作区工具循环属于 AgentOS 的 pack，复用现有 NodeRunner；没有新建 WorkflowRuntime 或任务数据库。

ExecutionPermit 在 Adapter 调用前验证；文件工具在审批前、审批后和派发前再次调用同一 invocation guard。模型不能声明 root、Grant、resource、沙箱档位或测试 executable。`run_tests` 仅接受测试路径，由可信配置编译为指定 Python 的 `-m pytest` 命令。

文件与测试动作逐条冻结于现有 Value Store。一次模型决策可返回最多 6 条动作，最多 32 条执行动作；每条具有稳定操作键，不并行扩展调度系统。失败测试返回实际退出码，节点可据此修改并复测。结束前必须有真实文件变更、最近一次测试完成且未超时、退出码为 0，并经同一 HMAC 读取最终文件快照。

## 4. Hands 安全与一致性修复

| 项目 | 实现 |
|---|---|
| executionId 所有权 | GET 状态、增量事件、POST cancel 都在签名验证后检查 callerId；另一合法凭据也不能访问 |
| 收据 checksum | 正常、失败、取消、恢复收据统一使用排除 checksum 字段的同一算法；加载、挂接和 AgentOS 消费端均校验 |
| 单写者 | Windows `CreateFileW` 排他共享锁，进程退出由 OS 释放；不依靠 PID 文件抢锁 |
| 撕裂尾行 | 保留隔离副本、截断到最后完整换行后再追加；完整坏行直接拒绝加载 |
| 终态一致性 | fsync 的 receipt 行定义终态；冲突收据拒绝；旧终态缺收据恢复为 UNKNOWN |
| 执行身份 | runId / stepId / attemptId / commitId 保留在 request summary、receipt、恢复投影中 |
| 文件读取约束 | 对 read/list 增加授权工作区 realpath 检查，使用通过检查的路径；既有写入隔离继续保留 |
| Shell cwd | 将相对 workdir 按授权工作区解析和校验，再把该绝对路径交给 DSH，避免按 Node 启动目录解释 |
| 生命周期 | 正常停止先请求取消并等待所属执行结束，再释放 Ledger 和 World |

HMAC、Grant、幂等、Job Object、vendor ACL 实现、UNKNOWN 保守语义均保留。Windows 本轮还复现了 PID 复用：旧测试 Java PID 被其他程序使用，脚本拒绝发信号。进程辅助函数现按创建时间识别旧进程已消失，不会停止其 PID 后继；同一创建身份下 executable/command 不符仍拒绝操作。

## 5. 显式合同适配与证据流

- `resourceId` 由 AgentOS 选择，不作为 Hands wire 字段发送；Grant 引用来自可信配置。
- requestId 从稳定 idempotencyKey 派生，避免客户端重建 requestId 改变同一次重试的正文。
- HMAC 兼容现有调用方秒级 timestamp 与 Hands 既有毫秒格式；签名始终覆盖原 timestamp，不降低时效或 nonce 校验。
- patch 的字段名显式转换；读取 `text → content`，stdout/stderr 对象转换为文本及截断标志，原封章收据保持原样。
- POST 202 只代表接收；通过状态和增量事件等待终态，校验 checksum、身份、Grant、请求关联和终态一致性。
- 明确协议/鉴权拒绝与 UNKNOWN 分开。接收后网络失联、缺失/无效收据、UNKNOWN 均不能作为成功，也不进入工具自动重放分支。
- executionId、checksum、receiptRef、Run/Step/Attempt/Commit 和 bindingId 写入现有工具审计/输出/Trace；完整 request、admission、receipt 使用现有 execution_values，不新增任务真源。
- 下游仅从自己 ContextPack 中声明接收的 receiptRef 消费收据；运行时复核 checksum 与身份后进入已有 `toolObservations` VERIFIED_EVIDENCE 通道。没有把其他节点的数据集合、文件工具或 Shell 权限直接授予核验与报告 Agent。
- canonical final 仍由既有 AgentOS artifact_generation、Identity/Artifact 与内容仓库生成、封章和展示。

## 6. 原生运行与数据隔离

统一入口：[README-EX-M1](../../ops/scripts/infra/windows/native/README-EX-M1.md)。

```powershell
$profileHome = "$env:LOCALAPPDATA\ZhiyiNative\ex-m1-20261029"
.\ops\scripts\infra\windows\native\persistent.ps1 up -HomeDir $profileHome -Desktop
.\ops\scripts\infra\windows\native\persistent.ps1 status -HomeDir $profileHome
.\ops\scripts\infra\windows\native\persistent.ps1 down -HomeDir $profileHome
```

本轮端口：PostgreSQL 15632、Memurai 16579、Python 18961、Hands 18965、Java 18280、Vite 15400、桌面 CDP 19422。

`-Backend hands` 在独立进程启动 Hands；默认 `python` 保留旧 Local Runtime。Workspace 和 Grant 固定在独立 Home；Hands Ledger 位于 `hands-ledger/`，Workflow SQLite 位于 `data/`，二者分离。凭据使用 DPAPI；临时 Hands keys JSON 在启动健康检查后删除，停止时再次清理。

Java 新增的审批 Gateway 路由沿用现有鉴权与内部传输。Maven `zhiyi.build.directory` 支持独立构建，本轮 JAR 位于 `artifacts/windows/pr-ex-m1/backend-build/`，不覆盖正在运行的 default JAR。该路径通过测试 Home 的 backendJar 固定，重启复用。

Shell 模式为可信配置明确选择的 host-approved / confinement=none，具有 Job Object，**不宣称 ACL Shell 沙箱**；审批界面保留原有风险提示，没有自动从 ACL 模式降级。vendor ACL 能力及真实 Windows 测试保留。

## 7. 真实验收记录

正式联调的业务写入发生于独立测试 Home/Workspace，回归使用各自独立的临时夹具。没有通过 Chat 或人工预写最终任务文件。源码、pytest 与辅助配置均由正式 ACG 调用 Hands 写入。

保留的阶段证据：

- `run_76c758709a8e` / `mission_bffa348f4c02`：四节点 completed；真实 pytest 首次 exit=1，导入失败；经界面批准创建 conftest 后复测 exit=0，`21 passed in 1.16s`。canonical 报告因缺少运行时核验观察判为 partial，此 Run **不作为完整 ACCEPT**。
- [该 Run 的正式 API 快照](../../artifacts/windows/pr-ex-m1/before-restart-run.json)、[原始交付物](../../artifacts/windows/pr-ex-m1/before-restart-output.json)、[签名查询核验收据](../../artifacts/windows/pr-ex-m1/before-restart-hands.json)、[Trace](../../artifacts/windows/pr-ex-m1/before-restart-trace.json)、[Provenance](../../artifacts/windows/pr-ex-m1/before-restart-provenance.json)。
- 独立真实服务在 STARTED 后崩溃，重启查询 UNKNOWN；更换客户端 requestId 重发同一执行仍不重放，外部目标未创建。另一真实命令经 HMAC 取消返回 CANCELLED、checksum 有效，延迟写入未发生；进程、端口、临时 keys 已清理。
- 另以真实服务验证读取字段转换、stdout 转换及实际 cwd 等于授权工作区：[异常与 cwd 最终证据](../../artifacts/windows/pr-ex-m1/exception-cwd-final.json)。

### 最终空目录正式任务

为排除已有文件影响，先停机，逐一验证测试文件哈希、进程身份、空闲端口及无 reparse point，再将先前工作区完整归档到测试 Home 的 `workspace-history/run_4a39d0d21b45`。没有删除文件或业务记录。原授权路径重新建立为空目录，参见 [归档与空目录证明](../../artifacts/windows/pr-ex-m1/archived-test-workspace.json)。

最终身份：

- Mission：`mission_e14852d8dc9a`；Run：`run_f123b0153e53`。
- Graph：`initial_646ec1267ea7f18ad616261be2a9a020a94b8d9f` v1；4 个节点、6 条边。
- Permit：`xpermit_1e8f89053069cd184c6680afc532f284f016e887`。
- Hands 所属 Step：`workspace_developer`；Attempt：`attempt_43868dae54cf`；resourceId：`n01a-host`。
- Commit：`commit:run_f123b0153e53:workspace_developer:0:generation:agen_7e7fd8200608f59afa920164bb5b820c`。
- 正式 V2 canonical Artifact：`artifact_7a6eea9f22d4`，artifactKey=`final`，producerAttempt=`attempt_c69d9dd28a49`。
- ContentManifest：`manifest_700c6515ea154ef98656c4ddfe8c11a2`。
- Markdown SHA-256：`8b2f1ad86b51f3cf8725ccf52f3f79dbae6ab5042f555e6efd85390fc535736f`。

注意：旧 capture JSON 的 `canonicalArtifact.artifactId=artifact_a1849db9bdfa3769` 来自内容封套，不能替代 V2 Identity。原始快照没有改写；已修正捕获工具以后分开记录 contentArtifactEnvelope 与正式 canonicalArtifact。上述正式 V2 身份来自重启后的真实界面与 Identity 库，[原始绑定记录](../../artifacts/windows/pr-ex-m1/canonical-identity.json) 的 created_at 为重启前的 `2026-10-29T08:05:27+00:00`，且 manifest/checksum 与重启前封章内容一致。

| 用户验收项 | 结果 | 实际证据 |
|---|---|---|
| 1. Planner 合法 TaskPlan / 正式 ACG 图 | PASS | 真实模型规划；图准备、激活成功；4 节点、6 边；[Run/API](../../artifacts/windows/pr-ex-m1/empty-before-restart-run.json) |
| 2. 正式 ExecutionPermit 后执行 | PASS | 界面依次完成交接、申请许可、Dispatch；Permit/Graph/Run 对应 |
| 3. ACG Agent 工具实际到达 Hands | PASS | 11 条真实执行收据，全部关联同一 Run/Step/Attempt/Commit；[收据](../../artifacts/windows/pr-ex-m1/empty-before-restart-hands.json) |
| 4. 创建与修改实际源码/测试 | PASS | 空目录内 fs.write 的 operation 均为 create：text_processor.py 725 B、tests/test_text_processor.py 1852 B、pytest.ini 79 B。此前独立正式 Run 还证明 update 与失败后修改 |
| 5. 真实 pytest 返回退出码和输出 | PASS | executionId=`xhexec_19db91e352599913170c88bf`；exitCode=0；stdout=`20 passed in 0.03s`；无超时/中止 |
| 6. 必要时根据失败修改复测 | PASS | 同轮保留的 `run_76c758709a8e` 中，真实 exit=1 导入错误 → 经审批写入 conftest → exit=0、21 passed；没有把最终空目录 Run 冒充为失败修复场景 |
| 7. 正式界面进度、绑定、工具事件和终态 | PASS | [Trace](../../artifacts/windows/pr-ex-m1/empty-before-restart-trace.json)、[Provenance](../../artifacts/windows/pr-ex-m1/empty-before-restart-provenance.json)、[完成界面](../../artifacts/windows/pr-ex-m1/empty-completed-desktop.png) |
| 8. 收据身份关联和副作用证据 | PASS | 11 份 checksum 验证；写入与测试后文件读取快照匹配；文件哈希另行捕获；没有把接收执行当作完成 |
| 9. canonical Markdown 包含变更/测试/证据 | PASS | [封章 Markdown 原文](../../artifacts/windows/pr-ex-m1/empty-before-restart-final.md)、[内容 API](../../artifacts/windows/pr-ex-m1/empty-before-restart-output.json)、正式 V2 canonical 绑定 |
| 10. 正常停机重启后查看原结果 | PASS | [重启比较](../../artifacts/windows/pr-ex-m1/restart-comparison.json)：Run、outputRef、内容 hash、数据库数量、文件 hash、凭据 hash、11 份收据一致，无新增执行；[重启界面](../../artifacts/windows/pr-ex-m1/restarted-final-desktop.png) |

pytest.ini 只设置 `testpaths=tests`、`python_files=test_*.py`、`python_functions=test_*`，没有屏蔽失败、跳过测试或模拟结果。

冷重启证据：[之前](../../artifacts/windows/pr-ex-m1/empty-before-restart.json)、[之后](../../artifacts/windows/pr-ex-m1/empty-after-restart.json)。完整封章收据均由正式 HMAC GET 重新查询，不只依赖磁盘文本比较。

验收结束后隔离服务已停止，数据保留：7 类所属进程均已退出，测试端口全空闲，Hands writer.lock 和临时 keys JSON 不存在，13 份 SQLite 可排他打开、Workflow OS 锁释放，DPAPI 持久凭据保留供下次启动使用。证据：[最终清理](../../artifacts/windows/pr-ex-m1/final-cleanup.json)、[生命周期关闭检查](../../artifacts/windows/pr-ex-m1/final-cleanup-verified.log)。没有停止或清理 default 环境。

## 8. 回归与保留失败

| 验证 | 当前记录 |
|---|---|
| Hands Windows 真实测试 | 串行 95/95 PASS，含 HMAC、Job、ACL、恢复、所有权与 Ledger；[日志](../../artifacts/windows/pr-ex-m1/hands-tests-serial-final.log) |
| Hands TypeScript | PASS；[日志](../../artifacts/windows/pr-ex-m1/hands-typecheck-complete.log) |
| Java 控制器与架构 | 38 PASS；[日志](../../artifacts/windows/pr-ex-m1/backend-regression.log) |
| Python 适配、原生 Agent、审计、值存储、证据与完成策略 | 最终组合 72 PASS，1 项既有 Pydantic 弃用警告；[日志](../../artifacts/windows/pr-ex-m1/python-72-final.log) |
| Vue desktop 类型检查 | PASS；[日志](../../artifacts/windows/pr-ex-m1/frontend-types-final.log) |

保留并说明失败，不将它们混记为通过：

1. 初始上下文未穿过 GuardedToolRuntime，工具调用前失败；已修复并增加包装链回归。
2. 模型连续多个 JSON 对象导致 Extra data；改为一个对象内的有界动作数组，逐条冻结执行。
3. fs.read 的 text/content 差异造成模型反复读取；已显式转换并以真实 HTTP 回归验证。
4. 真实模型连接曾被远端重置，运行失败记录保留，没有伪造节点完成。
5. controlPolicies 被现有 Planning Commit 的 safe-cut 门禁拒绝；没有放宽门禁。验收使用当前支持的有限图，文件修复复测发生在已有执行节点内部。
6. 既有“原样重跑”确认阶段出现 `explicit semantic plans require an unchanged trusted parent package` 409；未伪造恢复或绕过父包校验。
7. 并发 Hands 测试曾有两项 1 秒启动观测失败；未改超时或弱化 Job 断言。串行完整复验 95/95 通过，原日志 [保留](../../artifacts/windows/pr-ex-m1/hands-tests-cwd.log)。
8. 模型在测试已通过后仍重复复测并耗尽预算；已改为运行时根据真实变更、测试结果与最终快照结束节点。回归中使用真实临时文件和真实 pytest，证明不依赖模型返回 finish。

## 9. 剩余边界

- N01A Windows symlink 创建权限限制沿用为已知风险，不改为 PASS；未放宽路径策略。
- 本轮证明的是受审批的本机开发执行，confinement=none 不保证恶意测试代码只能访问 Workspace；未来启用严格 Shell ACL 需要独立处理既有 Windows 子进程限制。
- 既有 failed-Run 原样重跑父包校验 409 仍需后续修复；UNKNOWN 的对账与禁止自动重放不受其影响。
- canonical 报告如实保留 Python/pytest 版本、通信图回执等未进入其证据输入的元数据缺口；工程验收另有实际 TaskPlan/Permit/API、依赖安装记录和文件哈希，不改写模型原报告来制造无缺口结论。
- 既有 context-packs 可选查询仍有 404；正式 Run、图、工具事件、Artifact、Provenance 与收据主链可用。未扩展这项独立查询功能。
- 尚未覆盖 POSIX writer lock 的实际运行，也不将 Windows 结果推广到其他操作系统。
- Memurai Developer 的开发测试许可证和最大连续运行限制仍适用。
- Electron 接入、安装包、签名、自动更新、系统服务及多工作区动态授权不在本轮实施范围。

## 10. 源码修改与下一阶段依赖

| 范围 | 文件与作用 |
|---|---|
| Hands 单仓服务 | `apps/hands/`；auth、engine、service、ledger、world、writer-lock 与安全/一致性回归；protocol、grants、events、vendor 边界继续复用 |
| AgentOS 适配与工具循环 | `apps/agentOS/src/adapters/hands_http.py`；`apps/agent/app/tools/formal_workspace.py`；`apps/agent/packs/workspace/`；显式协议转换、系统授权/审批、真实工具与收据 |
| NodeRunner / 审计 / 存储 | `node_runner.py`、`audited_tool_runtime.py`、`guarded_tool.py`、`value_store.py`；上下文/Permit guard 透传、只读收据消费、不可变操作值和安全事件身份 |
| 原生模型调用 | `adapters/model/native.py` 接入已有 verified-evidence prompt 通道；`openai_runtime.py` 增加不含正文的 JSON 解析诊断 |
| 应用与 Java Gateway | `wiring.py` 按配置选择后端；`agentos_v2.py` 暴露现有审批队列；`AgentOsReviewController.java` 转发审批；pom 支持独立构建输出 |
| 真实前端 | `plugins/index.ts` 能力包选择、`FormalToolApprovals.vue`、`FormalExecutionControls.vue`；复用现有用户鉴权与审批 |
| 开发入口 | `persistent.ps1`、`persistent_runtime.py`、`native_runtime.py`；独立端口/数据、Hands 进程、Java JAR、临时凭据及安全停止 |
| 验收复现 | `persistent_checks.py` 扩展原 N03 捕获与对账；`hands_checks.py` 真实异常/取消/字段转换/cwd；`test_hands_integration.py` 控制与证据回归 |
| 桌面兼容 | Cargo 增加独立开发 binary，调用原应用 library；没有迁移桌面业务逻辑或实现 Electron |

下一阶段应先处理 failed-Run 的可信父包重跑兼容，再将已有独立服务入口接到用户正在实施的 Electron 宿主；统一进程管理、桌面目录选择和授权状态展示可复用本轮 HTTP/HMAC/Grant，不需要新增执行系统。安装包、服务注册、签名与更新仍需单独实施。严格 Shell ACL 模式须解决已有受限 token 子进程问题，不能静默改权限或降级。
