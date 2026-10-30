# PR-EX-M1 ~ M2B 执行闭环与动态工作区授权：实施与验收合并记录

> **文档性质**：阶段证据合并稿——实施与验收 3 篇 + 自测验收 1 篇
>
> **覆盖时间**：2026-10-29 ~ 2026-10-30
>
> **当前定位**：Hands 正式执行闭环、工作区编辑器与动态工作区授权
>
> **前置文档**：[PR-EX-00 执行后端架构审计与设计](PR-EX-00-执行后端架构审计与设计.md)（独立保留，本册不合并）
>
> **合并日期**：2026-10-30

## 0. 合并说明与导读

本册把 **PR-EX-M 系列（2026-10-29 ~ 2026-10-30）** 的 4 篇记录合并为一篇：Hands 单仓整合与正式执行闭环、工作区文件编辑器、Electron 动态工作区授权、动态工作区 ACG / Hands 端到端验收。正文逐字保留原文，仅做两类机械处理：标题层级下移一级、指向已合并文档的相对链接改写。来源清单见文末附录。

**设计基线不在本册**：[`PR-EX-00-执行后端架构审计与设计.md`](PR-EX-00-执行后端架构审计与设计.md) 是未实施的协议取舍与 `ExecutionBackend` 端口设计，仍作为独立文档保留，是理解本系列「为什么这样接 Hands」的前置阅读。

### 0.1 这一阶段在解决什么

S03 系列解决了「图能激活、状态能交接」，但**真正执行**仍缺一个统一后端：远程执行只有单射 HTTP RPC，没有会话、事件流、取消与对账。M 系列做了四件事：

1. **M1 单仓整合**：把 Hands 导入 `apps/hands`，打通 `Permit → Scheduler/Binder → NodeRunner 工具循环 → Hands HMAC → DSH World → 磁盘` 的正式执行闭环，并做冷重启一致性验收。
2. **M1 编辑器**：让工作区具备基础文本编辑能力——Main 只认登记文件夹 ID，Renderer 不传 `allowedRoot`；Ctrl+S 用版本比较 + 保存队列 + 临时替换。
3. **M2 动态工作区授权**：用户自主选择真实 Windows 目录，后端签发 `workspaceId` / `grantId`，每 Run 冻结 `workspaceBinding`，审批后与执行前各复检一次。
4. **M2B 端到端验收**：把 Electron → 动态授权 → ACG → Hands 写文件 / 跑测试 → canonical → 冷重启整条链跑通，同时如实保留 FAIL 与 BLOCKED。

### 0.2 一页结论

| 篇目 | 性质 | 结论 | 关键证据 |
|---|---|---|---|
| M1 单仓整合 | 实施与验收 | **ACCEPT**：正式执行主链与冷重启通过 | `run_f1230153e53` 空目录建 3 文件、pytest 20 passed、11 份收据；Hands 95/95、Java 38、Python 72 |
| M1 编辑器 | 实施与验证 | 通过（7 项 PASS），定位为基础文本编辑器 | Java 41、Python 3、前端 33、Electron 14、Hands 95/95 |
| M2 动态授权 | 实施与验收 | 动态授权链路真实验证通过，但未跑完整 ACG Mission，**未给整体 ACCEPT** | `..` 403、撤销 `revoked=true`、current 立即为空；Grant 与 Run 绑定冻结 |
| M2B 端到端 | 自测验收 | **SELF-TESTED**：存在明确 FAIL 与 BLOCKED，不作独立 ACCEPT | 授权/隔离 9 项 PASS；`run_e59fe12d8bf6` 14 份收据、13/13；Hands 门禁 94 PASS / 1 FAIL |

> M 系列的口径比 N 系列更保守：M2B 明确写「不作独立 ACCEPT」，并把 symlink BLOCKED 与内部 junction 合同 FAIL 分开登记。

### 0.3 贯穿全阶段的不变量

- **内核持全部权威**：外部执行后端只以 Receipt / ArtifactRef 进入，不能签发 Mission、Run、Permit 或交付身份。
- **模型不能提交授权字段**：工作区、Grant、允许根目录由 Main / 后端决定，Renderer 不传 `allowedRoot`。
- **每 Run 冻结绑定**：`workspaceBinding` 在审批后与执行前各复检一次，撤销立即生效。
- **单一收据账本**：执行事实以 HMAC 收据与台账去重落盘，冷重启后 Run、文件、收据保持一致。
- **如实登记 FAIL**：`confinement=none` 不是 OS 沙箱；symlink 无法创建时不改用 junction 或 Mock 冒充通过。

### 0.4 明确未完成与下一阶段入口

- **执行隔离不是 OS 沙箱**：`confinement=none`；symlink 夹具在 Windows 上 `WinError 1314`，真实链路 BLOCKED。
- **Hands 内部 junction 合同与测试不一致**，门禁 1 项 FAIL 未修；`run_tests` 的 npm 场景只作补充证据。
- **审批超时无显式对账恢复**；`diff --check` 的 CRLF 非零退出属工具差异。
- 编辑器无语言服务 / 搜索 / 新建改名删除，单文件上限 16 MiB，无跨进程事务锁。
- 安装包、系统服务、代码签名、多工作区并发不在本系列范围。
- 下一阶段：Electron 桌面宿主与 NSIS 安装验收见 [`PR-EL-01-Electron桌面宿主-合并记录.md`](PR-EL-01-Electron桌面宿主-合并记录.md)。

### 0.5 阅读建议

M1 看正式链路与冷重启证据；编辑器一篇看「Main 只认登记文件夹 ID」的权限收敛；M2 看 Grant 冻结与撤销；M2B 看真实端到端与保留失败。不要把 M2B 的 13/13 当成整体验收通过——它只覆盖相应 Run 的交付与收据。

## 篇目与阅读顺序

1. **PR-EX-M1：AgentOS × Hands 单仓整合与正式执行闭环** — 实施与验收，2026-10-29 — 原文件 `PR-EX-M1-AgentOS-Hands-单仓整合与正式执行闭环-实施与验收.md`
2. **工作区文件编辑器与自主选目录实施记录** — 实施与验证，2026-10-29 — 原文件 `PR-EX-M1-工作区文件编辑器-实施与验证.md`
3. **PR-EX-M2 Electron 动态工作区授权与 Hands 全链验收** — 实施与验收，2026-10-29 — 原文件 `PR-EX-M2-Electron-动态工作区授权与Hands全链验收.md`
4. **PR-EX-M2B：动态工作区 ACG / Hands 端到端验收** — 自测验收（SELF-TESTED），2026-10-29 ~ 10-30 — 原文件 `PR-EX-M2B-动态工作区ACG-Hands端到端验收.md`

---

## 1. 原文｜PR-EX-M1：AgentOS × Hands 单仓整合与正式执行闭环

<!-- 原始记录：PR-EX-M1-AgentOS-Hands-单仓整合与正式执行闭环-实施与验收.md -->

> 原文件 `PR-EX-M1-AgentOS-Hands-单仓整合与正式执行闭环-实施与验收.md` ｜ 2026-10-29 ｜ 实施与验收 ｜ 原文 20719 字节

日期：2026-10-29；平台：真实 Windows 11。**结论：ACCEPT——本轮正式执行主链与冷重启验收通过。**

最终任务从空测试工作区开始，真实创建 3 个文件，pytest 20 项通过，11 份执行收据校验通过；重启后 Run、内容、文件及收据保持一致。已知未通过项与架构限制见第 9 节，不将其混记为通过。

### 1. 基线与保护范围

- 主仓开工 HEAD：`145726f0a08f9a9ee4acc8255d785c8f10848a5b`；开工工作区干净。
- 原 Hands 仓库：`C:\Users\LZX\Desktop\zhiyi Hands`，HEAD `c48f704b2599102775668739f8838274a2a77068`；未修改、删除、归档或提交该仓库。
- 已阅读 EX-00、Hands 00/01/02 和实际 ResourcePlane、Binder、NodeRunner、AuditedToolRuntime、LocalRuntimeClient、ExecutionPermit、Hands protocol/engine/service/ledger/grants/events/World。
- N03 `default` 不参与本轮任何启停、初始化、恢复或数据写入。本轮独立 Home：`%LOCALAPPDATA%\ZhiyiNative\ex-m1-20261029`。
- default 的 `environment.json`、`credentials.dpapi`、`workspace/n03-persistent.txt` 哈希与开工记录一致。暂停期间部分进程发生外部重启，不能声称其 PID 始终未变；本轮未终止这些进程。
- 未修改 Docker 部署、历史数据库、数据卷、系统服务、ACL、开发者模式或系统权限。未提交或推送 Git。
- 用户正在进行 Tauri → Electron 迁移；本轮复用现有桌面验收，未实施 Electron 接入。此前为并行验收增加的 `kinlin-integration-dev` 只是同一 Tauri library 的独立开发 binary，避免覆盖 default 正在使用的 executable。

证据：[基线保护](../../artifacts/windows/pr-ex-m1/default-before.json)、[保护复核](../../artifacts/windows/pr-ex-m1/default-protection.json)、[导入核验](../../artifacts/windows/pr-ex-m1/import-verification.json)。

### 2. 单仓目录和依赖

`apps/hands/` 导入原仓 138 个 tracked 文件，并追加边界加固与回归。保留独立 package.json、pnpm-lock.yaml、tsconfig、Vitest、service/CLI、历史报告、DSH vendor、MIT LICENSE、PROVENANCE。

未导入 `.git`、node_modules 或原仓临时 evidence。历史报告中的旧证据属于原仓，不能作为本轮通过依据。100 个 vendor 文件逐一 SHA-256 比较未变化。新的安装、构建和服务启动仅引用本主仓路径。

- 安装：`pnpm --dir apps/hands install --frozen-lockfile`
- 类型检查：`pnpm --dir apps/hands typecheck`
- Windows 回归：`pnpm --dir apps/hands exec vitest run --maxWorkers=1 --fileParallelism=false`
- 独立服务：`pnpm --dir apps/hands service --config <受控配置文件>`

来源：[INTEGRATION-PROVENANCE](../../apps/hands/INTEGRATION-PROVENANCE.md)、[原始导入清单](../../artifacts/windows/pr-ex-m1/import-manifest.json)。

### 3. 正式调用链与权威边界

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

### 4. Hands 安全与一致性修复

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

### 5. 显式合同适配与证据流

- `resourceId` 由 AgentOS 选择，不作为 Hands wire 字段发送；Grant 引用来自可信配置。
- requestId 从稳定 idempotencyKey 派生，避免客户端重建 requestId 改变同一次重试的正文。
- HMAC 兼容现有调用方秒级 timestamp 与 Hands 既有毫秒格式；签名始终覆盖原 timestamp，不降低时效或 nonce 校验。
- patch 的字段名显式转换；读取 `text → content`，stdout/stderr 对象转换为文本及截断标志，原封章收据保持原样。
- POST 202 只代表接收；通过状态和增量事件等待终态，校验 checksum、身份、Grant、请求关联和终态一致性。
- 明确协议/鉴权拒绝与 UNKNOWN 分开。接收后网络失联、缺失/无效收据、UNKNOWN 均不能作为成功，也不进入工具自动重放分支。
- executionId、checksum、receiptRef、Run/Step/Attempt/Commit 和 bindingId 写入现有工具审计/输出/Trace；完整 request、admission、receipt 使用现有 execution_values，不新增任务真源。
- 下游仅从自己 ContextPack 中声明接收的 receiptRef 消费收据；运行时复核 checksum 与身份后进入已有 `toolObservations` VERIFIED_EVIDENCE 通道。没有把其他节点的数据集合、文件工具或 Shell 权限直接授予核验与报告 Agent。
- canonical final 仍由既有 AgentOS artifact_generation、Identity/Artifact 与内容仓库生成、封章和展示。

### 6. 原生运行与数据隔离

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

### 7. 真实验收记录

正式联调的业务写入发生于独立测试 Home/Workspace，回归使用各自独立的临时夹具。没有通过 Chat 或人工预写最终任务文件。源码、pytest 与辅助配置均由正式 ACG 调用 Hands 写入。

保留的阶段证据：

- `run_76c758709a8e` / `mission_bffa348f4c02`：四节点 completed；真实 pytest 首次 exit=1，导入失败；经界面批准创建 conftest 后复测 exit=0，`21 passed in 1.16s`。canonical 报告因缺少运行时核验观察判为 partial，此 Run **不作为完整 ACCEPT**。
- [该 Run 的正式 API 快照](../../artifacts/windows/pr-ex-m1/before-restart-run.json)、[原始交付物](../../artifacts/windows/pr-ex-m1/before-restart-output.json)、[签名查询核验收据](../../artifacts/windows/pr-ex-m1/before-restart-hands.json)、[Trace](../../artifacts/windows/pr-ex-m1/before-restart-trace.json)、[Provenance](../../artifacts/windows/pr-ex-m1/before-restart-provenance.json)。
- 独立真实服务在 STARTED 后崩溃，重启查询 UNKNOWN；更换客户端 requestId 重发同一执行仍不重放，外部目标未创建。另一真实命令经 HMAC 取消返回 CANCELLED、checksum 有效，延迟写入未发生；进程、端口、临时 keys 已清理。
- 另以真实服务验证读取字段转换、stdout 转换及实际 cwd 等于授权工作区：[异常与 cwd 最终证据](../../artifacts/windows/pr-ex-m1/exception-cwd-final.json)。

#### 最终空目录正式任务

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

### 8. 回归与保留失败

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

### 9. 剩余边界

- N01A Windows symlink 创建权限限制沿用为已知风险，不改为 PASS；未放宽路径策略。
- 本轮证明的是受审批的本机开发执行，confinement=none 不保证恶意测试代码只能访问 Workspace；未来启用严格 Shell ACL 需要独立处理既有 Windows 子进程限制。
- 既有 failed-Run 原样重跑父包校验 409 仍需后续修复；UNKNOWN 的对账与禁止自动重放不受其影响。
- canonical 报告如实保留 Python/pytest 版本、通信图回执等未进入其证据输入的元数据缺口；工程验收另有实际 TaskPlan/Permit/API、依赖安装记录和文件哈希，不改写模型原报告来制造无缺口结论。
- 既有 context-packs 可选查询仍有 404；正式 Run、图、工具事件、Artifact、Provenance 与收据主链可用。未扩展这项独立查询功能。
- 尚未覆盖 POSIX writer lock 的实际运行，也不将 Windows 结果推广到其他操作系统。
- Memurai Developer 的开发测试许可证和最大连续运行限制仍适用。
- Electron 接入、安装包、签名、自动更新、系统服务及多工作区动态授权不在本轮实施范围。

### 10. 源码修改与下一阶段依赖

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

---

## 2. 原文｜工作区文件编辑器与自主选目录实施记录

<!-- 原始记录：PR-EX-M1-工作区文件编辑器-实施与验证.md -->

> 原文件 `PR-EX-M1-工作区文件编辑器-实施与验证.md` ｜ 2026-10-29 ｜ 实施与验证 ｜ 原文 6194 字节

日期：2026-10-29。基线 HEAD：`88c04151`。本轮未提交 Git。

### 已实现

右侧“文件”现可打开 Windows 原生文件夹选择器，自主选择本机目录。点击文件在中央编辑区打开独立标签，与 canonical Artifact 标签并存。提供行号、Ctrl+S、保存按钮、未保存标记、Tab 缩进、重新读取、关闭/离开前确认；文件内容按文本呈现，不执行 HTML。切换标签保留草稿。

手动选定的文件夹不依赖启动脚本固定工作区，也不依赖 Python/Hands 的编辑版本令牌。显示隐藏目录和依赖目录，按展开动作读取目录。支持 UTF-8 文本（最大 16 MiB），原生操作仍受当前 Windows 用户权限约束。二进制和其他编码有明确提示。

Main 仅接受原生选择器登记的文件夹 ID，Renderer 不传任意 allowedRoot。文件夹选择保存在当前 Electron userData 的 `workspace-folders.json`，重启恢复。手动编辑使用窄 IPC 文件接口，未添加命令执行、Planner 或 Agent Loop。保存使用内容版本比较、同一进程同一文件的保存队列、同目录临时文件替换；外部冲突拒绝并保留草稿，不自动重试不确定保存。

启动时任务工作区的正式 API 路径也保留：Vue → Java JWT Gateway → Python Mission ownership/工具权限 → LocalRuntimeClient → Hands HTTP/HMAC/Grant。补充 Java 的 list/read/save 转发；规范 Hands 目录返回的相对路径。版本化读取与 expectedVersion 条件写入复用 DSH 合同。人工 Save 仅在该次已认证请求内通过原有权限服务解决一次 fs.write 审批；DENY 仍拒绝，不创建 session 授权。

选择编辑目录不等于给 Agent 自动执行新增 Grant；ACG、ExecutionPermit 和自动工具审批保持原合同。当前选目录功能服务于手动文件编辑。

### 真实 Windows/Electron 验证

独立 Home：`%LOCALAPPDATA%\ZhiyiNative\ex-m1-20261029`。端口：Java 18280、Python 18961、Hands 18965、前端 15400、Electron CDP 19422。未切换 default 环境或改动系统服务。

| 验证 | 结论 | 证据 |
| --- | --- | --- |
| 真实 Windows 原生选择器选择 Runtime 根目录外文件夹 | PASS | 使用 Windows UI Automation 操作实际“打开工作文件夹”对话框；目录为 artifacts/windows/workspace-explorer/user-selected-folder |
| 文件树、中央标签、隐藏目录、切换标签 | PASS | electron-editor-after-restart.png；verify-editor.js |
| Ctrl+S 写入实际磁盘 | PASS | user-selected-folder/hello.py；acceptance.json 的 SHA256 |
| 外部修改后拒绝旧版本保存、草稿保留 | PASS | prepare-conflict.js、verify-conflict.js、electron-conflict-final.log |
| 未保存时取消关闭，草稿保留 | PASS | verify-reload-save.js、electron-reload-save.log |
| 正常退出并重启桌面后恢复目录和文件 | PASS | electron-close.log、electron-restart.log、electron-restart-e2e.log、electron-editor-after-restart.png |
| 原任务工作区经 Java/Python/Hands 真实保存并恢复原文 | PASS | electron-hmac-save-restored.log；测试 Home ai.log 中 workspace/file 两次 POST 200；临时 probe 注释已恢复 |

证据目录：`artifacts/windows/workspace-explorer/`。测试窗口留在所选目录，便于人工检查。测试区内只写入独立样例；未更改 default 用户文件。

### 回归

- Java：41 项通过，java-editor-tests.log；隔离 JAR 构建通过，backend-editor-build.log。
- Python API：3 项通过，python-editor-final.log；包含越界拒绝、旧版本不写入、一次审批及请求不能声明 allowedRoot。
- 前端：33 项通过，frontend-editor-tests-final.log；Electron 模式 vue-tsc 通过。
- Electron：14 项通过，electron-editor-tests-final.log；包含真实文件 I/O、隐藏目录、原生保存、恢复、二进制拒绝、冲突及并发保存只有一方成功。TypeScript 通过。
- Hands：最终串行 95/95，hands-editor-serial-final.log；TypeScript 通过。
- 首次 Hands 并行 93/95，两项短超时探针未观察到启动输出。原始日志 hands-editor-tests.log 保留；单文件复验 16/16、最终全套串行 95/95，没有修改命令超时或安全策略。
- 原始截图等待和全局草稿等待的超时记录保留；后续独立截图、作用域内检查、磁盘内容及 HTTP 日志确认结果。不可把早期超时日志单独视为全部验收通过。

### 源码范围

- `apps/desktop/electron/src/lib/workspace-files.ts`、`ipc-contract.ts`、`main.ts`、`preload.ts`、对应原生 I/O 测试：人工选目录、记忆和文件操作。
- `apps/frontend/src/components/workbench/WorkspaceFileEditor.vue`、Explorer、EditorGroup、MissionWorkspaceView、workspace 类型/API、Electron bridge：文件树和中央编辑标签。
- Java Observation/Mission Controller 和 Observation 测试、Python agentos_v2 与 API 测试：原任务工作区接口。
- Hands engine/providers/world、Python LocalRuntimeToolExecutor：显式版本化读取与条件保存字段。
- `persistent_runtime.py`：偏移测试实例使用独立 Electron userData，避免与 default 单实例锁冲突。
- 工作区并行出现的 `native_runtime.py` 修改及 `migrate_from_docker.py` 不属于本功能，没有覆盖或清理。

### 使用与范围

在桌面项目页点击右侧“文件”→“打开文件夹”→选择目录→点文件→中央编辑→Ctrl+S。无需编辑 .env、重启 Runtime 或重新创建 Grant。

当前是基础文本编辑器，还没有 VS Code 的语言服务、语法诊断、全局搜索、文件新建/重命名/删除。不同编码和超大文件需要后续扩展。外部进程与保存之间采用乐观版本校验，不宣称跨所有外部程序的事务锁。手动编辑的操作不冒充 ACG 节点证据，canonical final deliverable 仍由 AgentOS 管理。动态切换 Agent 的执行工作区还需要正式的 Grant 绑定流程。

本轮没有开展安装包、系统服务、权限提升，也没有提交或推送 Git。

---

## 3. 原文｜PR-EX-M2 Electron 动态工作区授权与 Hands 全链验收

<!-- 原始记录：PR-EX-M2-Electron-动态工作区授权与Hands全链验收.md -->

> 原文件 `PR-EX-M2-Electron-动态工作区授权与Hands全链验收.md` ｜ 2026-10-29 ｜ 实施与验收 ｜ 原文 3010 字节

本轮在 PR-EX-M1 的 Electron 唯一桌面宿主和 Hands 正式执行链之上，增加用户选择真实 Windows 项目目录的动态授权闭环。

### 已实现

- Electron Main/Preload/PlatformAdapter 目录选择仍只返回候选路径；后端 `WorkspaceAuthority` 在现有 PostgreSQL/Flyway 中校验目录、规范化大小写、拒绝 `..` 与 reparse point，并签发稳定 `workspaceId` / `grantId`。
- 授权记录绑定用户、租户、资源和 Grant，支持查询、撤销和重启恢复。每个 Run 创建时冻结 `workspaceBinding`；工具审批后及执行前重新校验撤销状态、根身份和 Grant。
- Hands 服务按可信 Grant 的 canonicalRoot 选择动态 World；模型输入不能提供 `allowedRoot`、`grantId`、`workspaceId`、`resourceId` 或安全档位。`confinement=none` 继续标注为 host-approved，明确不是 OS 沙箱。
- `run_tests` 支持受信任的 Python `pytest`、Node `node --test` 和 `npm test`，收据保存 executable、argv、workdir、退出码、stdout/stderr、超时和取消状态。正式测试命令失败会让执行失败，不能把接收或非零命令当成功。
- 工作台显示当前工作区、授权风险、待授权目录和撤销按钮；文件浏览使用已冻结 Run 的授权上下文。

### 真实验证

独立 Home：`%LOCALAPPDATA%\\ZhiyiNative\\ex-m2-20261029`；Backend=hands；端口偏移 400；独立 Electron user-data、PostgreSQL、Memurai、Hands ledger 和项目目录。N03 default 未参与启停。

- `persistent.ps1 init/up/status -Desktop`：PostgreSQL、Memurai、Hands、Python、Java、Vite、Electron 均由独立 Home 启动并健康。
- Electron 登录测试账户后，`/api/agentos/v2/workspaces/current` 返回未授权状态；通过实际 Electron 前端授权 API 选择 `projects/python-project`，返回 `workspaceId`、`grantId`、root identity 和风险标记。
- 选择 `..` 路径被后端以 403 `Parent traversal is forbidden` 拒绝；授权后撤销返回 `revoked=true`，current 立即为空。
- Python 编译、Java Maven package、Electron 14 项测试、前端 `vue-tsc`、WorkspaceFileEditor 测试通过；Hands 回归保留历史 shell receipt 语义，正式测试命令单独按非零退出失败。

### 与 M1 的边界

M1 验收固定启动工作区和 Hands 正式执行/冷重启；M2 扩展为用户目录选择、可信后端动态 Grant、Run 冻结、撤销生命周期和 Python/Node 测试命令。仍不实施安装包、服务、自更新、签名或商业发布，不覆盖 N03 default 数据。

### 剩余风险

Windows 普通权限下 symlink/junction 夹具能力受系统策略限制；实现按真实 `lstat/realpath` 和 reparse 检查 fail-closed。`confinement=none` 仍是宿主权限命令模式，不宣称 OS 沙箱。完整 ACG Mission 需要真实模型凭据和人工审批队列；本轮已验证授权、撤销、路径拒绝和运行时绑定链路。

---

## 4. 原文｜PR-EX-M2B：动态工作区 ACG / Hands 端到端验收

<!-- 原始记录：PR-EX-M2B-动态工作区ACG-Hands端到端验收.md -->

> 原文件 `PR-EX-M2B-动态工作区ACG-Hands端到端验收.md` ｜ 2026-10-29 ~ 10-30 ｜ 自测验收（SELF-TESTED） ｜ 原文 25329 字节

日期：2026-10-29—2026-10-30。状态：**SELF-TESTED，存在明确 FAIL 和 BLOCKED；不作独立 ACCEPT 结论**。

本记录基于 Windows 真实进程、Electron 界面、真实 DeepSeek 模型、正式 Run、HMAC HTTP 和磁盘文件。组件回归与真实端到端证据分开列出。入场及最终 HEAD 为 master `f7700affdc9f3b7173521bc94819c6b09e31c210`；没有 commit、push、merge 或部署。

原始证据目录：[artifacts/windows/pr-ex-m2b-20261029](../../artifacts/windows/pr-ex-m2b-20261029)。其中初次失败、诊断、后续修复和复验日志均保留，不以最后一次通过覆盖早期失败。

### 1. 入场与保护边界

已读取 M1、文件编辑器、M2、EX-00、HANDS-02 报告、最近三个提交完整 diff，以及本轮任务指定的真实实现。没有重做 M1，也没有引入第二个 Runtime、Workspace 数据库、Scheduler 或执行账本。

入场已有前端 package/lock、ChatView、WorkspaceFileEditor 和 syntaxHighlight 修改；详见 `git-status-before.txt`、`preexisting-files.json`。没有恢复、覆盖或暂存这些文件。实施期间另有用户并发修改编辑器、状态栏、ProblemsPanel、EditorGroup 和 MissionWorkspaceView；这些不计入本轮源码修复。最终回归另行覆盖当前前端，不沿用旧前端快照结论。

保护 default、ex-m1-20261029、ex-m2-20261029 的环境配置、DPAPI、Grant 及 runtime-state，11 个文件摘要核对见 `protected-before.json`、`preservation-current.json`。没有对这些环境执行启停、恢复、迁移或业务写入。原有容器资产的状态沿用入场代码，本轮未操作 Docker、旧数据卷或系统服务。

当前 Windows 令牌未提权，缺少 SeCreateSymbolicLinkPrivilege，开发者模式未配置，见 `windows-token-readonly.json`。未提权、未修改开发者模式、未放宽 ACL。原生 Python 环境实际缺少 requirements.txt 已声明的 psycopg，补装缺失的 3.3.6 依赖并修复锁文件；未重建或删除共享 Python 环境，也未升级其他已有依赖。

### 2. 隔离环境及实际调用链

Home：`%LOCALAPPDATA%\ZhiyiNative\ex-m2b-20261029`，初始化前确认不存在。独立 PostgreSQL cluster、数据库身份、Memurai、SQLite、Hands Ledger、Electron user-data 和项目目录；JAR 使用本轮证据目录下独立 build 输出，未覆盖运行中的 default JAR。

| 服务 | 本轮端口 |
| --- | --- |
| PostgreSQL / Memurai | 16032 / 16979 |
| Python / Hands | 19361 / 19365 |
| Java / Vite / Electron CDP | 18680 / 15800 / 19822 |

真实链路：Electron Main/Preload 目录选择 → PlatformAdapter → 登录用户 Workspace API → Java 身份与内部鉴权转发 → PostgreSQL V12 WorkspaceAuthority → Run 冻结 workspaceBinding → Planning Commit → Graph Materialization/Activation/Handoff/ExecutionPermit/Dispatch → Scheduler/ResourceBinder/Lease → NodeRunner 内 AgentOS 工具循环 → FormalWorkspaceTools 审批 → HandsHttpTransport HMAC → 独立 Node HandsService → Grant 解析的 Execution World → 磁盘/测试进程 → checksum/身份核验 → Value Store、Trace、Provenance → canonical Artifact。

Electron 本地目录登记只支持用户手动文件操作，不签发 Agent 执行 Grant。模型不能提交根目录、Grant、resourceId 或安全档位。`confinement=none` 明确是 **host-approved 宿主用户权限执行，并非 OS 沙箱**；npm 项目脚本本身具有宿主权限，必须审查项目和命令。

统一入口（复用已初始化的本轮 Home，不要重新 init）：

```powershell
$entry = '.\ops\scripts\infra\windows\native\persistent.ps1'
$testHome = "$env:LOCALAPPDATA\ZhiyiNative\ex-m2b-20261029"
& $entry up -HomeDir $testHome -Desktop
& $entry status -HomeDir $testHome
& $entry down -HomeDir $testHome
# 仅非正常退出后使用，保留原数据：
& $entry recover -HomeDir $testHome -Desktop
```

### 3. 最小源码修复

| 范围 | 真实缺陷与修复 |
| --- | --- |
| `apps/hands/hands/engine.ts` | 通用 executable 分支在执行后引用不存在的 `input`，导致真实命令已运行却生成 ReferenceError 失败收据；改用 `request.input`。 |
| `apps/hands/hands/ledger.ts`、`tests/service-ledger.spec.ts` | 终态 receipt 行恢复未应用时间戳，冷启动后 updatedAt 倒退至 STARTED。恢复 receipt 行时同步 updatedAt，原重启测试新增精确比较。 |
| `apps/agentOS/src/support/acg/capabilities.py`、新增 scoped optional dependencies 回归 | Workspace pack 注入的可选依赖在 pack 不启用时悬空，真实规划 STALE_STRATEGY。scoped 副本仅过滤不在作用域的可选边，强制依赖仍验证，原 catalog 不变。 |
| `apps/agent/app/api/agentos_v2.py` 与既有 API 测试 | 动态文件读取查询 Run 时未传可信 owner，已登录用户仍得到“Mission has no frozen workspace Run”。传入 user/tenant 过滤，新增所有者可读、他人隐藏且不触发文件传输的回归。 |
| Java Workspace/Observation/Review Controller、Support、异常处理及 workspace projection DTO/mapper | 严格 QueryProjection 门禁发现原始 Object/Map 输出、审批查询未投影及 legacy 文件错误 detail 不匹配。显式白名单 DTO 保留正式响应语义；WorkspaceController 加入严格检查，没有降低断言或新增豁免。 |
| `apps/agent/requirements.in`、`requirements.lock` | WorkspaceAuthority 新依赖未进入锁文件，真实启动 ModuleNotFoundError。固定 psycopg/psycopg-binary 3.3.6 并保留发行包 hash，独立 venv 验证 require-hashes 安装。 |
| `ops/scripts/infra/windows/native/persistent_checks.py` | 旧 capture 仅扫描 init 默认 workspace，无法证明动态目录磁盘结果。改为读取现有 Run 的冻结绑定，同时保留 startupWorkspace 字段；未建立新真源。 |
| README-EX-M1、README-N03、EL-01 报告 | 补充历史验收范围说明，链接本报告；旧 M1 固定工作区证据不代表 Electron 动态授权已通过。 |

没有修改 ExecutionPermit、Attempt、Checkpoint、UNKNOWN、工具审批、WorkspaceAuthority 的授权策略、DSH vendor 或路径隔离策略。测试辅助脚本均在本轮证据目录，复用生产 transport、既有 persistent_checks 和 hands_checks，不作为新运行系统。

### 4. 动态授权与安全边界

| 验收 | 结果与证据 |
| --- | --- |
| 未授权状态、Windows 原生目录选择、正式信任 | PASS；实际 Electron 注册/登录，原生 Windows 目录对话框选择 `projects/node-project`，再由正式 API 授权。不是通过页面注入路径伪造原生选择。UI 日志、截图及 `authorization-boundaries.json`。 |
| 冻结身份 | PASS；workspace `ws_ddf49cdccad0d5459bd5ca131a2a5ba6d924e6d4a6f3bcf5`，grant `wgrant_7c798a6b41194ed8ae862e8c76aa79ff`，resource `n01a-host`，rootIdentity `7127730056805780013:1407374883930853`；用户/租户与 PG V12 行及 Run 相符。 |
| 路径规范化和越界 | PASS；大小写路径得到同一 workspace/Grant；含 `..` 授权请求 403；真实 junction 根 403；外部哨兵保持不变。 |
| 真实 symlink | BLOCKED；普通权限创建夹具 WinError 1314。未以 junction 或 Mock 替代此项。 |
| 取消待信任目录 | PASS；真实选择外部测试候选后取消，原有效授权保留；`cancel-candidate-ui.log`。 |
| 用户/租户隔离和权威字段伪造 | PASS；未登录拒绝、其他用户不能读取 Mission/撤销 Grant，其他可信租户无选择且不能撤销；六种保留授权字段 422。租户测试经真实内部服务边界，不将客户端伪造 header 当租户权威。 |
| 撤销与重新授权 | PASS；旧 Run 403；同一根重新授权产生新 Grant，旧 Run 继续 403；伪造重跑 binding 422。`authorization-lifecycle.json`。 |
| 根目录身份替换 | PASS；原测试目录重命名并在同一路径新建目录，旧 Run 403 identity changed；原目录与替换目录哨兵均未修改。 |
| Permit 后、派发前撤销 | PASS；真实模型 Run `run_c259761f0ec3`，Permit `xpermit_83ce9f560a0a4742ea78539d911bfadcf3adffe4`；撤销后正式派发不能执行工作区操作，文件摘要不变、无对应 Hands claim。`revocation-before-dispatch.json`。 |
| 审批等待期间撤销 | 源码确认审批返回后重新检查 guard/authority；本轮未单独制造“审批待决时撤销”的真实窗口用例，不将源码检查冒充该用例通过。 |

### 5. 真实 Mission：失败、修复、复测与交付

测试输入是可丢弃 Node 项目，基线 reverseText 错误返回原字符串，已有断言要求 abc→cba。基线文件摘要见 `project-before.json`。后续源码和测试结果由 ACG/Hands 实际生成，未人工预写完成文件。

#### 5.1 首次审批超时的失败保留

Mission `mission_328918d01fdc`，Run `run_e2e9e0bac505`，Permit `xpermit_2bf441241cb36f58057dd113c9b38eea5320e3d6`。只有四份 read/list 收据；首次 node 测试审批在用户响应前按既有 300 秒期限到期，Run FAILED，无写入或命令 admission。没有调整超时、自动补批或重放。

真实 UI 恢复分别被“Permit retry must retain its formally activated Run”和“unsettled external operation requires explicit side-effect reconciliation”拒绝。保留 409，不编辑旧 Run；这是当前保守恢复能力的实际限制。确认没有写/命令 admission 后另建正式 Mission，重新申请 Permit。

#### 5.2 正式开发 Run

Mission `mission_d5fcefb6390f`，Run `run_e59fe12d8bf6`。通过真实 Electron 创建、规划、准备图、激活暂停、交接、Permit、执行，用户在真实界面批准四项写/命令操作。

- Hands 读取现有项目，真实 `node.EXE --test` 首次退出 1（abc 不等于 cba），收据 `xhexec_61382afd5f23e854d09553d2`。
- Hands 写入 `src/text.js` 和 `test/text.test.js`，实现字符串反转、回文判断、单词统计与测试。
- 真实复测退出 0，13/13，通过收据 `xhexec_9107e6dd7f5e4eff2130c92c`；失败输出确实反馈给执行节点，没有把 202 当成功。
- 14 份收据均以生产 HMAC 查询并验证 checksum、Run/Step/Attempt/Commit。错误目录 tests 的 FS_NOT_FOUND 与首次测试失败均保留。
- Run completed，但本次额外任务要求的 patch_file、npm-test 没执行，canonical **准确标为 PARTIAL**，也指出上游不准确的 Python 开发摘要；因此不将该 Run 描述成全部要求通过。
- canonical V2 identity `artifact_9d3ca06c36c3`，producerAttempt `attempt_57bc9633b10d`，manifest `manifest_6151749338c8482db7a022616916a6a1`，18897 字节，SHA-256 `290c0585b182807a7dfe62c7404dc222b3c29c24bbd4a0384c340d4bcee1daa7`。

证据：`completed-main-capture.json` 及同前缀 run/output/hands/trace/provenance/final 文件。Markdown 是通过正式输出引用从应用取回，并非人工生成交付物。

#### 5.3 补充正式 patch / npm Mission

用户后续明确授权由执行代理逐项审查并点击真实界面的“允许本次操作”。仍通过原审批 UI，不调用后门自动批准或改变 ASK 策略。

第一次补充规划 `run_7c763d7cbb8d` 被 CONTROL_BARRIER_BLOCKED 拒绝，未执行；保留 trace，不放宽控制策略。改为明确顺序任务，真实 Electron 创建 Mission `mission_61793feb3a01`、Run `run_7c0dee91a6fd`，Planner 接受四节点任务图。

Permit `xpermit_3e274c9a97a1d51a271f5636a9afc0c61049e6c6`，Planning Commit `pcommit_f17527975c3d4123ac585f352d5d6957`，graph `initial_9df51483f20e5d9e3e043b9ede164ead482e00b6` v1。通过正式 UI 检查并批准 `npm.cmd test` 基线、源码 patch、测试 import patch、测试新增 patch 和最终 npm 复测。

Hands 在同一冻结工作区追加 normalizeWhitespace，检查非字符串 TypeError、Unicode 空白与 trim，增加四项测试。最终收据、canonical 和冷重启比较见本报告末尾补充结果及原始 capture。

#### 5.4 额外真实协议与故障回归

- `python-runner-signed-regression.json`：独立测试目录由真实 Workspace API 授权，生产 HMAC/Hands transport 执行五次操作，pytest 1 failed → fs.patch → pytest 1 passed；记录命令、退出码、输出与 checksum。**这是协议回归，不是另一个正式 ACG Mission**。
- 复用 `hands_checks.py`，真实独立进程在 STARTED 后异常退出，恢复 UNKNOWN；同幂等键及变化客户端 requestId 均不重放，未知文件不存在。真实取消产生 CANCELLED 封章收据，无延迟副作用；所属进程、19366 端口和临时 key 清理通过。详见 `exception-checks.json`。

### 6. 回归与原始失败

组件 pytest 使用已具备测试依赖的 Windows Python 3.14（`%LOCALAPPDATA%\Programs\Python\Python314\python.exe`）；服务使用 N03 原生 venv，项目 pytest 使用本轮独立 test-python venv。三者分开，不把组件测试解释为服务验收。AgentOS pytest 在 `apps/agentOS` 执行，设置 `PYTHONPATH=src;..;../agent;.`；Agent API pytest 在 `apps/agent` 执行。

| 门禁 / 命令范围 | 最后已完成结果 | 日志 |
| --- | --- | --- |
| 前端 NativeWorkspacePicker/Chat/Editor 定向 vitest | exit 0，27 PASS | frontend-focused.log |
| 前端工作区视图定向 vitest | exit 0，31 PASS | frontend-workspace-focused.log |
| 前端完整 `npx vitest run --maxWorkers=1 --fileParallelism=false` | 首轮完整 110 文件 / 735 PASS；并发修改后的最终复验另见末尾 | frontend-expanded-final.log、frontend-final-snapshot.log |
| Vue Electron 类型检查 | exit 0 | frontend-types-final.log |
| Electron `npm test` / `npm run typecheck` | exit 0，14 PASS / 类型通过 | electron-tests.log、electron-types-final.log |
| Java `mvn test`（独立 build directory）及 package | exit 0，191 PASS，0 skip；独立 JAR 构建通过 | java-expanded-fixed2.log、java-final-package.log |
| Python Agent Workspace/API 定向与扩大 pytest | exit 0，58 PASS | python-api-final.log |
| AgentOS Permit/审计/初始规划/Hands adapter/optional scoped pytest | exit 0，65 PASS | agentos-expanded-correct-cwd.log |
| AgentOS 完整 Permit/审计/初始执行许可/规划来源/恢复/Hands/audited tool/scoped 扩大 pytest | **exit 0，122 PASS** | agentos-complete-expanded-final.log、agentos-complete-expanded-final.exit.txt |
| AgentOS executor 全目录及 scoped 回归 pytest | exit 0，25 PASS | agentos-node-runner-expanded.log |
| Hands focused service/ledger 与 engine 相关回归 | exit 0，28 PASS；时间戳修复后 ledger 12 PASS | hands-focused-fixed.log、hands-ledger-fixed.log |
| Hands `pnpm exec tsc --noEmit` | exit 0 | hands-types-final.log |
| Hands `pnpm exec vitest run --maxWorkers=1 --fileParallelism=false` | **exit 1，94 PASS / 1 FAIL** | hands-expanded-final.log、hands-expanded-final.exit.txt |
| 固定 psycopg hash 独立 venv 安装 | exit 0 | dependency-hash-validation-final.log |

Hands 未通过项：`tests/adversarial.spec.ts:81` 的内部 junction 正向控制期待 completed；当前 M2 World 拒绝全部 reparse point，实际 failed。外指 junction 拒绝及 ACL 外部写拒绝通过。没有删除测试、弱化断言或放宽路径隔离；此门禁仍是 **FAIL**，需要后续明确内部链接产品合同并使实现与测试一致，不能宣布全绿。

另保留：初次缺 psycopg 启动失败、scope 悬空依赖导致的规划失败、engine input ReferenceError、Java 原始投影门禁失败、动态读取 owner 缺失、账本恢复时间戳差异。混合 pytest 从错误 cwd 启动产生 test_react_loop import setup ERROR，改为正确 cwd 后重跑通过；前端最初受负载影响的 streaming 测试失败/跨夜中断保留，后续完整重跑，不修改 timeout 或断言。

### 7. 冷重启、快照与最终状态

第一次正常 down/up 已确认四份只读收据、旧 Run、绑定与文件保留；同时发现 receipt updatedAt 恢复不一致并作上述最小修复。最终写入任务完成后的正常冷重启、当前前端快照、授权撤销状态与清理结果在下方追加；不得用首次只读 Run 的冷启动替代有副作用 Run 的验收。

当前已知限制：真实 symlink 夹具 BLOCKED；Hands 扩大门禁一项 FAIL；审批到期后的正式恢复仍需显式对账支持；host-approved Shell 不是 OS 沙箱；Memurai Developer 仍受 N03 已记录的开发许可证限制。本轮不涉及安装包、系统服务、自动更新、商业发布或独立验收。

#### 最终补充结果（2026-10-30）

**补充正式 Mission PASS。** Run `run_7c0dee91a6fd` completed，13 份完整 checksum/身份验证收据。开发 step `workspace_developer`、attempt `attempt_a13e6607c7c6`、commit `commit:run_7c0dee91a6fd:workspace_developer:0:generation:agen_d7cd677b2d59387621547dad698ef76c`。

| 操作 | 真实 executionId | 结果 |
| --- | --- | --- |
| npm 基线 | xhexec_5166c69b3a53286138a0cece | exit 0，13/13 |
| 源码补丁 | xhexec_b60829b8d39c80c1f0913e26 | fs.patch completed |
| 测试 import 补丁 | xhexec_51e44f076be220c87e15b880 | fs.patch completed |
| 测试用例补丁 | xhexec_6506bf88e2fb2e520e1598fb | fs.patch completed |
| npm 复测 | xhexec_1590f6ab9cbd7bf10649827e | exit 0，17/17 |

命令为可信配置的 `F:\Web\node-v24.19.0-win-x64\npm.cmd`，argv `["test"]`，workdir `.`（Grant 实际根是本轮项目），npm 项目脚本执行 `node --test`。完整 stdout/stderr、executable 身份、收据、时间和文件摘要见 `final-before-patch-hands.json`；未将接收请求或进程启动当作测试成功。

补充 canonical identity `artifact_4ec1352c7197`，producerAttempt `attempt_7be31289f05a`，manifest `manifest_85847cd824344e6bbc8107a76552e921`，SHA-256 `a5ceb625443d09c4d787c5ed9056e668a1f52de067b6ad015b3f396301853863`。报告准确纠正上游固定摘要中的 pytest 字样，以已验证 npm 收据为准；字面 patch 参数未出现在 receipt，报告明确将补丁展示标为前后快照重建。没有人工修改模型生成的 canonical Markdown。

**有副作用 Run 冷重启 PASS。** `final-cold-down.log` 正常停机，`final-cold-up.log` UP，之后分别通过生产捕获工具复查上述两次开发 Run：

- `final-before-main*` / `final-after-main*`：14 份收据、完整 Run、Trace、Provenance、output 和摘要完全相同。
- `final-before-patch*` / `final-after-patch*`：13 份收据、完整 Run、Trace、Provenance、output 和摘要完全相同，包括修复后的 updatedAt。
- 两次 capture 的 workspaceFiles SHA-256、冻结 Grant、canonical identity/manifest/Markdown checksum 全部一致。
- PostgreSQL 四条授权记录（包括 revoked 状态）逐字段一致，`final-before-authorizations.json` / `final-after-authorizations.json`。
- Ledger 仍为 236 行，SHA-256 `7b802472542e51c30fd6b0a0d220f673387371ed2266dc0edb43afb93bf49e4b`，没有新增 claim 或重复副作用。
- 冷启动后真实 Electron 显示原账户、已信任 node-project；打开历史 Run 的 final.md，canonical 身份仍一致。截图 [重启后交付物](../../artifacts/windows/pr-ex-m2b-20261029/final-canonical-after-cold.png)。

精确比较见 `final-cold-comparison-final.json`。初版辅助探针把整个 temp 目录非空误判成临时密钥未清理；实际剩余是 JVM/Tomcat/Node 缓存。保留初版 false 记录，最终按生产入口的三个真实临时凭据名称（pg-init-password、redis-auth.conf、hands-keys.json）检查，均不存在；没有为清理缓存而删除目录或业务数据。

**最终前端快照 PASS。** 并发修改稳定后，完整 vitest 再跑 110 文件 / 739 PASS，exit 0，`frontend-final-snapshot.log`；Electron vue-tsc 再跑 exit 0。`final-regression-source-start.json` 记录 2020 个源文件摘要；`preservation-final.json` 核对其未变。临时 LF 格式诊断后恢复 Hands 两文件原有 CRLF，最终内容与已运行回归快照一致；ledger 定向额外 12 PASS，未更改断言或时间阈值。

**Windows 空白检查说明。** 原样 `git diff --check` exit 2，仅把已有 CRLF 文件中新加行的 CR 报成 trailing whitespace。为避免把两份 Hands 文件整体转换为 LF（会造成数百行无意义 diff），保留原 CRLF；执行 `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check` exit 0，仍检查真正的行尾空格、文件尾空行和 tab 前空格。仅对该命令传入 CRLF 识别，没有修改仓库或全局 Git 配置。原样命令的非零结果保留在 `git-diff-check-final.log`，不能将其写成 exit 0。

最终判断：**SELF-TESTED：Electron 动态授权 → 正式 ACG → Hands 文件写入/补丁 → 测试失败修复复测 → canonical → 冷重启闭环已实际贯通。扩大 Hands 门禁仍 1 FAIL，真实 symlink 仍 BLOCKED，原样 diff 空白检查存在上述 CRLF 非零结果；不声明全部验收项通过。**

恢复遗留包括：审批超时后的显式对账与恢复入口、内部 junction 合同与测试不一致、模型开发摘要固定 pytest 说法（验证节点虽已纠正，仍属质量问题）、context-packs 查询 404（未阻断本轮，但会产生 UI 控制台错误）。安装包、服务管理、许可证生产化均不在本轮。

#### 最终清理及命令记录

`final-cleanup.log` / `final-cleanup.exit.txt`：本轮 Home 最终 **DOWN，exit 0**；所属 Electron/前端/Java/Python/Hands/Memurai/PostgreSQL 正常退出，进程及端口释放，数据库独占句柄和 Runtime OS 锁可获得，escalated 为空。DPAPI 和业务数据保留；临时凭据与持久 DPAPI 的清理语义不同。default/M1/M2 不参与此停止命令。

最终源快照比较 `source-snapshot-final-comparison.json`：2020 个已记录文件，无内容变化。`tracked-diff-source-sha256.json`、`git-status-final.txt` 和 `git-head-final.txt` 记录最终差异和摘要；原有用户前端修改与新增并发修改继续保留。报告和测试证据不包含明文测试密码、内部令牌或 HMAC key；精确匹配扫描见 `evidence-secret-scan.json`。

以下为本轮关键门禁命令；相应工作目录及 exit code 见上表与各日志，`$testPy` 指上述 Windows 测试 Python，`$nativePy` 指 N03 venv：

```powershell
# apps/frontend
npx.cmd vitest run src/components/platform/NativeWorkspacePicker.spec.ts src/views/ChatView.spec.ts src/components/workbench/WorkspaceFileExplorer.spec.ts src/components/workbench/WorkspaceFileEditor.spec.ts --maxWorkers=1 --fileParallelism=false
npx.cmd vitest run --maxWorkers=1 --fileParallelism=false
npx.cmd vue-tsc --noEmit -p tsconfig.electron.json
# apps/desktop/electron
npm.cmd test
npm.cmd run typecheck
# apps/backend；所有输出均指向独立目录
mvn.cmd '-Dzhiyi.build.directory=../../artifacts/windows/pr-ex-m2b-20261029/backend' test
mvn.cmd -DskipTests '-Dzhiyi.build.directory=../../artifacts/windows/pr-ex-m2b-20261029/backend' package
# apps/agent
& $testPy -m pytest -q tests/test_agentos_v2_api.py tests/test_agentos_v2_workspace_api.py
# apps/agentOS，PYTHONPATH=src;..;../agent;.
& $testPy -m pytest -q tests/components/executor tests/components/planner/test_scoped_optional_dependencies.py
& $testPy -m pytest -q tests/components/planner/test_execution_permit.py tests/components/planner/test_execution_permit_audit.py tests/components/planner/test_initial_execution_permit.py tests/components/planner/test_initial_planning_sources.py tests/components/planner/test_permit_recovery.py tests/components/planner/test_permit_recovery_final_audit.py tests/components/planner/test_scoped_optional_dependencies.py tests/adapters/test_hands_integration.py tests/adapters/test_audited_tool_runtime.py
# apps/hands
pnpm.cmd exec vitest run tests/service-auth.spec.ts tests/integration-hardening.spec.ts --maxWorkers=1 --fileParallelism=false
pnpm.cmd exec vitest run tests/service-ledger.spec.ts --maxWorkers=1 --fileParallelism=false
pnpm.cmd exec vitest run --maxWorkers=1 --fileParallelism=false
pnpm.cmd exec tsc --noEmit
# 仓库根；真实异常服务探针和动态 Run 捕获
& $nativePy ops/scripts/infra/windows/native/hands_checks.py --home $testHome --port 19366 --output artifacts/windows/pr-ex-m2b-20261029/exception-checks.json
& $nativePy ops/scripts/infra/windows/native/persistent_checks.py --home $testHome --run-id run_7c0dee91a6fd --output artifacts/windows/pr-ex-m2b-20261029/final-after-patch.json
```

收集命令额外确认了测试解释器的区别：N03 服务 venv 本身没有 pytest，故用它执行 collect-only 得到 No module named pytest；未为此向服务环境安装无关测试包。其日志保留，组件回归均使用实际测试 Python，不将失败收集算成测试通过。

完整 122 项回归于本轮最终快照上实际完成，149.65 秒、exit 0，没有跳过；这覆盖了此前错误 cwd 的 122 项集合，不能仅以较早 65 项替代此最终结果。最后核对 default/M1/M2 的 11 个受保护文件仍无变化，见 `protected-after-final-cleanup.json`。证据索引和源码摘要随本轮证据目录保存；测试 Home 保持停止，数据和正式交付物保留以供复核。

---

## 附录：来源清单与合并说明

| # | 原文件 | 日期 | 性质 | 原文大小 |
|---:|---|---|---|---:|
| 1 | `PR-EX-M1-AgentOS-Hands-单仓整合与正式执行闭环-实施与验收.md` | 2026-10-29 | 实施与验收 | 20719 字节 |
| 2 | `PR-EX-M1-工作区文件编辑器-实施与验证.md` | 2026-10-29 | 实施与验证 | 6194 字节 |
| 3 | `PR-EX-M2-Electron-动态工作区授权与Hands全链验收.md` | 2026-10-29 | 实施与验收 | 3010 字节 |
| 4 | `PR-EX-M2B-动态工作区ACG-Hands端到端验收.md` | 2026-10-29 ~ 10-30 | 自测验收（SELF-TESTED） | 25329 字节 |

> **合并规则**：正文逐字保留，仅做两类机械处理：(1) 标题层级下移一级，原文 H1 由本节标题替代；(2) 指向已合并 / 已归档文档的相对链接改写为新文件名。结论、数字、命令与代码块未改动。
>
> **完整性校验**：合并时对每篇原文做归一化比对（忽略标题层级与链接目标），本篇 4 篇全部一致。
>
> **恢复原件**：原文件已从当前目录移除，完整内容保留在 Git 历史中。整理提交前用 `git checkout HEAD -- "docs/开发记录/<原文件名>"`；提交后用 `git checkout HEAD~1 -- "docs/开发记录/<原文件名>"`。
