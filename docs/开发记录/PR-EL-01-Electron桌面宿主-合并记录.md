# PR-EL-01 Electron 桌面宿主：迁移与验收合并记录

> **文档性质**：阶段证据合并稿——迁移报告 1 篇 + 全栈验收报告 1 篇
>
> **覆盖时间**：2026-10-29
>
> **当前定位**：Electron 单壳为当前桌面基线；默认入口切换仍有两项放行条件
>
> **合并日期**：2026-10-30

## 0. 合并说明与导读

本册把 **PR-EL-01（2026-10-29）** 的 2 篇记录合并为一篇：Electron 桌面宿主全链路迁移报告、Electron 全栈验收报告。正文逐字保留原文，仅做两类机械处理：标题层级下移一级、指向已合并文档的相对链接改写。来源清单见文末附录。

### 0.1 这一阶段在解决什么

N03 之后，运行链已经是纯 Windows 原生栈，但桌面壳仍是 Tauri 过渡形态。EL-01 把桌面宿主迁到 **Electron 单壳**，目标是：

- 一个 Main 进程承担窗口、预加载与安全边界，**禁止 `child_process` 与执行器**；
- `kinlin-app://` 自定义协议 + 严格 CSP，渲染进程不直接触达 Node；
- 保留 Tauri 入口作为回退，独立 worktree 开发，不 push、不 merge、不切默认入口；
- 迁移报告只证明「宿主可开发 / 可运行 / 可打包 / 能连 Runtime」，**不证明业务链已经验收**——这一层由验收报告补齐。

### 0.2 一页结论

| 篇目 | 性质 | 结论 | 关键证据 |
|---|---|---|---|
| 迁移报告 | 迁移与自测 | 宿主全链路实测通过，但登记 6 项未验证 | 前端 729/729、Electron 13/13、ops 15/15；安全门禁 16/16；NSIS 137.9MB 未签名构建成功 |
| 全栈验收 | 独立验收 | **CONDITIONAL ACCEPT**：默认桌面入口切换暂缓 | N02 全栈 PASS、N03 备份 1372 文件 / recover 0；真实业务链 RUN completed 2/2、SSE 4 事件；未授权 `C:\Windows` 403 |

> 迁移报告与验收报告的差异本身就是结论：迁移证明「壳能用」，验收才证明「业务链能用」，但安装包实测仍缺席。

### 0.3 贯穿全阶段的不变量

- **Main 进程最小权限**：门禁检查 Main 不得引入 `child_process` 与执行器，渲染进程走白名单 Preload。
- **协议与 CSP 收口**：只允许 `kinlin-app://` 加载，禁用任意远程内容。
- **入口不切换**：验证在独立 worktree 完成，默认入口保持 Tauri 回退。
- **不把构建成功当安装成功**：NSIS 构建成功 ≠ 安装 / 升级 / 卸载已验收。

### 0.4 明确未完成与放行条件

- **NSIS 安装实测 BLOCKED**：未安装、未升级、未卸载，安装包未签名。
- **OS 拖放与 UI 审批人工点验**未完成。
- 迁移阶段留下的 6 项未验证（含 9050 网关未运行导致业务流未验证、N02/N03 全栈壳未拉起）由验收报告补测，但仍有环境限制。
- 验收会话的 console-ctrl 失效，优雅停止改用等价手工步骤，未按标准路径演练。
- 放行条件只有两条：完成 NSIS 安装实测 + 完成拖放与审批人工点验；满足后才切换默认入口。

### 0.5 阅读建议

先读迁移报告的「架构决策」与「未验证项」，再读验收报告的「逐项结果」与「结论与放行条件」。若只想知道「现在能不能把 Electron 设为默认」，看验收报告的终判与放行条件即可。

## 篇目与阅读顺序

1. **PR-EL-01 Electron 桌面宿主全链路迁移报告** — 迁移报告，2026-10-29 — 原文件 `PR-EL-01-Electron桌面宿主迁移报告.md`
2. **PR-EL-01-ACCEPTANCE Electron 全栈验收报告** — 独立验收报告，2026-10-29 — 原文件 `PR-EL-01-ACCEPTANCE-Electron桌面验收报告.md`

---

## 1. 原文｜PR-EL-01 Electron 桌面宿主全链路迁移报告

<!-- 原始记录：PR-EL-01-Electron桌面宿主迁移报告.md -->

> 原文件 `PR-EL-01-Electron桌面宿主迁移报告.md` ｜ 2026-10-29 ｜ 迁移报告 ｜ 原文 11281 字节

> 本文保留 EL-01 历史迁移验收范围，不代表动态工作区和 Hands 正式开发已经验收。
> 后续基于主仓当前代码的 Electron + WorkspaceAuthority + ACG/Hands 联调、回归及剩余问题见
> [PR-EX-M2B 验收记录](PR-EX-M1-M2B-执行闭环与工作区授权-合并记录.md)。

日期：2026-10-29　分支：`pr-el-01-electron-host`（独立 worktree `../kinlin_ai-el01`，基于 master `145726f0`）

### 结论

Electron 桌面宿主已落地并可开发、可运行、可打包、可连接现有 Runtime：开发模式与打包版均在本机
真机打开过窗口并经 CDP 取证；窗口三键、F11、最大化状态同步、状态持久化、Preload 白名单桥、
渲染沙箱、外链协议校验全部实测通过。Web/Tauri 构建模式零破坏（全量前端回归 729/729、Web 构建通过）。
Tauri 入口原样保留为回退路径。执行系统（另一合并任务）的合同、调度、审批、Attempt Fence、
Checkpoint、GraphVersion、Workspace Grant 一律未触碰。

### 基线

- 起点：master `145726f0`；工作区未提交改动（执行系统合并任务的 12 M + 8 ?? 文件）原样保留在主工作区，未读取、未修改。
- 本任务全部改动发生在独立 worktree/分支，无 push、无 merge。
- 工具链：Node 24.19.0、Electron 45.1.0（Chromium 156.0.8078.49）、electron-builder 26.18.0、esbuild 0.28.2。

### 架构决策

1. **Desktop Host 边界**：Electron Main 只负责窗口、原生交互、桌面生命周期与日志；无 `child_process`、
   不内嵌执行器/Scheduler、不直接调用模型（新增 agentOS 架构门禁强制，见下）。
2. **前端沿用 PlatformAdapter 合同**：新增 `platform/electron/` 三件套（adapter/uiZoom/drag-region.css）
   经既有 `@platform`/`@ui-zoom`/`@window-controls` 别名按 `--mode electron` 切换；窗口控件新增
   `ElectronWindowControls.vue`（与 Tauri 版同模板同样式，桥实现不同）。业务 UI、Workbench、ACG、
   Mission、Chat 零改动。
3. **生产加载协议**：注册为 standard+secure 的自定义协议 `kinlin-app://`，页面 Origin 固定
   `kinlin-app://shell`，资源从 asar 内 `renderer/` 提供（路径穿越防护 + 无目录列表 + HTML 注入 CSP）。
   CSP 比 Tauri 版更紧：script-src 无 `unsafe-eval`、全串无通配符来源。
4. **端口与代理**：Electron 开发模式复用 15100（与 Tauri dev 同端口同 CORS 白名单，互斥使用）；
   N02/N03 仍是 15200。生产默认网关 `http://127.0.0.1:9050`（`KINLIN_API_ORIGIN` 可覆写，CSP 同步）。
5. **Native 抽象**：新增 `desktop_shell.py` 把「拉起桌面壳 + 识别窗口」抽象为 tauri/electron 双实现，
   `KINLIN_DESKTOP_SHELL` 选择、默认 tauri；两个 runtime 只换调用点，身份校验/端口检查/停止语义不动。
6. **并存身份**：appId `com.kinlin.zhiyi.electron`、产品名 `Zhiyi AgentOS Electron`、快捷方式
   「知弈 AgentOS Electron」，与 Tauri 版（`com.kinlin.zhiyi`）安装/卸载完全隔离。

### 文件变更

**新增（Electron 工程 `apps/desktop/electron/`）**：`src/main.ts`（主进程）、`src/preload.ts`（沙箱
contextBridge）、`src/lib/{ipc-contract,validation,window-state,logging,app-assets,protocol}.ts`（纯逻辑
+ 协议/CSP）、`test/*.test.ts`（node --test 13 例）、`scripts/{dev,copy-renderer}.mjs`、`build.mjs`、
`electron-builder.yml`、`package.json`/`tsconfig.json`/`README.md`/`.gitignore`。

**新增（前端 `apps/frontend/`）**：`src/platform/electron/{bridge,adapter,uiZoom,drag-region.css}`、
`src/components/desktop/ElectronWindowControls.vue`、`src/platform/electron/{adapter,uiZoom}.spec.ts`、
`src/components/desktop/ElectronWindowControls.spec.ts`、`tsconfig.electron.json`、`.env.electron`。

**修改（前端）**：`vite.config.ts`（desktop 家族三路别名、15100 端口、`dist-electron` 产物目录）、
`package.json`（`dev:electron`/`build:electron` 脚本）、`src/platform/api.ts`（electron 模式的
prod/dev origin 规则与 desktop 一致）。

**修改（原生 N02/N03）**：`desktop_runtime.py`（桌面段换 desktop_shell 调用、show/close 类名参数化、
状态记 `shell` 字段、CORS 加 `kinlin-app://shell`）、`persistent_runtime.py`（同构改造）、
`desktop.ps1`/`persistent.ps1`（`-Shell electron` 开关）、`README-N02.md`/`README-N03.md`（桌面壳章节）；
新增 `desktop_shell.py`、`start-desktop-electron.ps1`、`ops/scripts/infra/tests/test_desktop_shell.py`（15 例）。

**修改（网关来源）**：`apps/backend/src/main/resources/application.yml`、`compose.yaml` 的 CORS 默认值
各加 `kinlin-app://shell`（Tauri 来源保留）。

**修改（测试门禁）**：`apps/agentOS/tests/architecture/test_capability_upgrade_gates.py` 新增
`test_electron_host_does_not_embed_execution_authority`（electron src 禁 `LocalRuntime`/
`ExecutionBackend`/`child_process`）；既有 Tauri 断言未动。

### 测试与验证结果

自动化（全部本机实跑）：

| 套件 | 结果 |
| --- | --- |
| 前端全量 vitest（含新增 16 例 electron spec） | 108 文件 / 729 例全过（123.6s） |
| Electron lib node --test（校验/窗口状态/CSP/协议路径） | 13/13 |
| ops pytest `test_desktop_shell.py` | 15/15 |
| agentOS 架构门禁（含新增 Electron 宿主断言） | 16/16 |
| `vue-tsc` electron 类型检查、`tsc` 主进程类型检查 | 通过 |
| `npm run build:web`（回归） | 通过，dist/ 正常 |
| `npm run build:electron` | 通过，产物 `dist-electron/`（不影响 Web dist） |
| `npm run pack` / `npm run dist` | win-unpacked 与 NSIS 安装包 `Zhiyi AgentOS Electron-0.1.0-x64-Setup.exe`（137.9MB，未签名）构建成功 |

真机取证（Electron 45 / 本机 Windows，经 `--remote-debugging-port` CDP）：

- **开发模式**：`scripts/dev.mjs` 自动起 Vite(15100, mode=electron)→Electron；页面
  `http://127.0.0.1:15100/#/login` 标题「登录 - 知弈AgentOS」；hash 路由（isDesktop 生效）。
- **打包模式**：win-unpacked 直启，页面 `kinlin-app://shell/index.html#/login`，Origin
  `kinlin-app://shell`，asar 加载正常，响应头带严格 CSP（实测读回）。
- **Preload 桥**：`window.kinlinDesktop` 键集与白名单逐项一致（window/zoom/dialog/notify/openExternal/appInfo）。
- **IPC 往返**：`isMaximized`→false、`appInfo`→{0.1.0, win32, packaged}；主进程参数校验拒绝
  `javascript:` 外链（实测错误串）。
- **渲染沙箱**：页面内 `process`/`require`/`global` 全部 undefined。
- **窗口三键**：toggleMaximize 往返 false→true→false；minimize 后 Win32 `IsIconic=True`（类名
  `Chrome_WidgetWin_1`，与 desktop_shell 匹配值一致）；close 干净退出（CDP 下线、进程 exit 0）。
- **F11**：keydown 往返 true→false（Electron 版为渲染进程键盘事件，等价 Tauri Rust global-shortcut）。
- **状态持久化**：最大化态重开自动恢复；`window-state.json` 落盘与末态一致（normalBounds 语义正确）。
- **生命周期**：关窗→app 退出；dev.mjs 退出时 Vite 进程树被清理、15100 释放（实测）。

### 未验证项（明确登记，不以模拟充数）

1. **NSIS 安装/卸载实测**：安装包已构建未在本机执行安装（避免向用户系统写开始菜单/注册表）；
   win-unpacked 已验证同一二进制可运行。人工验收：双击 Setup 或 `Setup.exe /S`。
2. **登录 / Mission / Run / Chat / SSE / WebSocket 业务流**：本轮宿主机 9050 网关未运行，页面
   只验证到登录墙渲染与桥/路由层。链路本身零改动（同 Vite 代理/同网关 origin 规则），
   待栈启动后走一遍即可。
3. **未授权工作区被 Host 拒绝**：属 Host Grant 权威，本轮未动其后端；目录选择 IPC 只返回候选路径
   的设计未变，待后端在位时随 N02 复验。
4. **N02/N03 全栈 Electron 壳 up/down/recover**：desktop_shell 产出的命令即本次真机验证的同款
   `node electron/cli.js <dir> --dev-server=… --remote-debugging-port=19222` 调用（15100 换 15200），
   类名匹配已真机证实；但完整原生栈（Docker PG relay、jar、venv）未在本轮拉起，未实测。
   入口：`desktop.ps1 up -RunDir … -Desktop -Shell electron` / `persistent.ps1 up … -Desktop -Shell electron`。
5. **原生缩放下 ACG 图交互 / 文件与目录选择对话框 / HTML5 拖放**：缩放经 `webFrame.setZoomFactor`
   （与 Tauri webview.setZoom 同语义，canvas 命中由合成器处理）；对话框为原生模态需人工点击；
   拖放沿用 Web 原生（Tauri 侧 `dragDropEnabled:false` 的等价行为，Electron 默认即 HTML5 拖放）。
   三项留给人工桌面验收。
6. **窗口按钮的鼠标点击**：以桥方法调用等价验证（同 IPC 通道同 handler）；像素级点击留人工。

### 已知问题

- 未配置代码签名证书（Tauri 版同样未签）；SmartScreen 可能提示，属既有基线。
- CSP 未含 `unsafe-eval`：若后续引入需要 eval 的依赖需重估（当前全量页面在打包版正常加载）。
- Electron dev 与 Tauri dev 共用 15100，二者不可同时跑（strictPort 快速失败，防静默漂移）。
- `window.kinlinDesktop` 的 Renderer 类型（bridge.ts）与 Preload 实现手工同构，改动需双侧同步
  （ipc-contract.ts 注释已标注）。

### 与执行系统合并任务的冲突点

- 主工作区未提交改动涉及的文件中，`ops/scripts/infra/windows/native/{persistent.ps1,persistent_runtime.py,native_runtime.py}`
  与本任务改动的同名文件在 worktree 基于 HEAD 修改。合并时预期冲突点：
  `persistent_runtime.py` 的 `up()` 桌面段与 CORS 行、`persistent.ps1` 参数块。解法：本任务的改动
  是把桌面段收敛为 `desktop_shell` 调用，语义包含旧逻辑，按本任务形态解冲突并保留对方执行系统的
  其他修改即可；`native_runtime.py` 本任务未改。
- `apps/frontend/src/plugins/index.ts`、`components/workspace/*` 等对方改动文件本任务均未触碰。
- CORS/白名单与应用层执行合同正交，无语义冲突。

### 残余 Tauri 依赖与回退说明

- Tauri 工程与入口完整保留：`apps/desktop/src-tauri/`、`start-desktop-hot.ps1`、`start-desktop-built.ps1`、
  `dev-hot-reload.bat`、`desktop.ps1 -Shell tauri`（默认值即 tauri）、`npm run dev:desktop`/`build:desktop`。
- 生产 backend/网关的 `tauri://localhost`、`http://tauri.localhost` 来源仍保留在白名单。
- Electron 验收通过前，桌面默认入口不变；要回退：不使用 Electron 入口即可，如需彻底移除，
  删除 `apps/desktop/electron/` 与 `ops/scripts/start-desktop-electron.ps1`，无共享文件残留
  （vite.config 的 electron 分支在 mode!=electron 时不生效）。
- 待 Electron 全量验收后再切换默认入口（届时单独一笔提交改 start-desktop 脚本指向）。

---

## 2. 原文｜PR-EL-01-ACCEPTANCE Electron 全栈验收报告

<!-- 原始记录：PR-EL-01-ACCEPTANCE-Electron桌面验收报告.md -->

> 原文件 `PR-EL-01-ACCEPTANCE-Electron桌面验收报告.md` ｜ 2026-10-29 ｜ 独立验收报告 ｜ 原文 8115 字节

日期：2026-10-29　分支：`pr-el-01-electron-host`（worktree `kinlin_ai-el01`，无新增功能改动）
前置：PR-EL-01 迁移六笔提交 `79ce3e85..1f9f33f8` 原样保留，未 push、未 merge、未切默认入口。

### 终判：CONDITIONAL ACCEPT

核心迁移准入项（N02 全栈、N03 持久环境、真实业务链路、原生交互、窗口控制）全部通过或经等价路径验证；
存在两项明确的非阻断限制（F 安装实测 BLOCKED、验收会话上下文的 console-ctrl 环境限制）。
**默认桌面入口切换建议暂缓**：待 NSIS 安装实测（需 Windows Sandbox/测试机）与 OS 级拖放人工点验后一并放行。

### 逐项结果

#### A 自动化测试与构建复核 — 通过

| 项 | 命令 | 结果 |
| --- | --- | --- |
| 前端全量 | `npm test`（apps/frontend） | 108 文件 / 729 例全过（123.6s） |
| Electron lib | `npm test`（apps/desktop/electron） | 13/13 |
| Native 抽象 | `pytest ops/scripts/infra/tests/test_desktop_shell.py` | 15/15 |
| 架构门禁 | `pytest apps/agentOS/tests/architecture/test_capability_upgrade_gates.py` | 16/16 |
| 后端 jar | `mvn -DskipTests package`（worktree） | 79,082,502B 成品 |
| Web/Electron 构建 | `npm run build:web` / `build:electron` | 均通过（前次会话，产物未变） |

#### B N02 Electron 全栈 — 通过（含一次外部环境中断取证）

一轮：`desktop.ps1 up -Desktop -Shell electron` → `status=UP`、`desktopShell=electron`、独立库 `n02_0c5c14ac23`、
Electron 窗口（CDP 19222，`登录 - 知弈AgentOS`）。期间 **Docker Desktop 被外部整体退出**（时间线：容器 14:44 全停 → 14:47 全起 → ~14:57 Docker 退出；docker pipe 不存在实证），`docker exec nc` 转发链断 → Java 报 `SQLState 08001 / HikariPool 超时`。该中断非 Electron/桌面壳缺陷。down 两段式：首跑六服务优雅停止超时登记（`desktop-down-errors.json`），进程随后自行退出；二跑正式 **PASS**（端口释放、SQLite 独占句柄核验、临时凭据清除、测试库保留）。

二轮（Docker 恢复后）：up → UP → 注册/登录/工作区绑定 200/200/200（docker relay 链 + Electron 窗口）→ down 两段式 → **PASS**，端口全释放。

#### C N03 持久环境 — 通过（身份/数据零变更）

- 状态检查：干净停止态（owned 进程全缺失），`environment.json`/`credentials.dpapi` 身份校验通过。
- 冷备份：`persistent.ps1 backup` → **PASS**（`snapshot-el01-accept`，1372 文件 + 逐文件 SHA-256）。
- `up -Desktop -Shell electron` → UP（Electron 窗口 + 全部原生服务）。
- `recover -Desktop -Shell electron` → exit 0，同身份重启（恢复能力 + 重复启动）。
- 数据持久性（重启后经窗口实测）：同账号登录 200 且 userId 一致；Mission 列表含本验收任务；
  Run `run_93c41ff86736` 保持 `completed`/2 outputs/`formalControl=ACTIVATED`。**未重建数据库、未轮换密钥、未清业务数据**（`persistentCredentialsRetained=true`）。
- 最终 down **PASS**（processesAbsent/portsReleased/databaseHandlesReleased/workflowLockReleased 全 true）。

#### D 真实业务链路 — 通过（经 Electron 渲染进程，N03 真实栈）

注册 200（sid JWT）→ 登录 200（独立 sid）→ token 后进入应用壳 `#/chat`（拖拽区在位）；
Workspace Grant：授权目录 `select` 200（`selected:true`）、**未授权 `C:\Windows` → 403 "outside the startup-issued Workspace Grant"**（Host 权威拒绝）；
文件上传 200（落库路径返回）、agentOS 附件 201（READY+sha256）；
Mission 语义创建 202（按真实合同补齐 `semantics`+`clientRequestId`，两次 422 校验错误如实记录）；
Run 生命周期 pending→planning→`PLANNING_ACCEPTED`（commitId 实锤）；
**正式控制五步**：materialize 200 `MATERIALIZED_INACTIVE` → activate 200 `ACTIVATED_PAUSED`（graphVersion 1）→ handoff 200 `STATE_PREPARED` → permit 200 `ISSUED` → dispatch 202 `ACCEPTED`（审批链全程 API 驱动）；
Run 真实模型执行 → **completed**（2/2 步、零错误、2 outputs）；ACG 图 `/runs/{id}/graph` 200（2 节点/1 边）；
Chat SSE `/ai/chat/text/stream` 200，真实模型流 4 事件（content_delta×2/usage/done）；
WS `/ai/realtime-asr` 连接被拒——与既有已知限制一致（Java 无语音 WS 端点，非 Electron 引入）。
UI 级交互审批（Chat 文件写入确认等）留人工，与 Tauri 版验收口径相同。

#### E 窗口与原生交互 — 通过

三键：toggleMaximize false→true→false、minimize 后 Win32 `IsIconic=True`（类名 `Chrome_WidgetWin_1`）、close 干净退出；
F11 全屏往返 true→false；缩放：视口 1456→1011 比值 **1.44（=1.2² 两档）**、Ctrl+0 复位精确回 1456；
原生文件对话框：IPC → Win32「打开」(#32770) → 取消 → null；原生目录对话框：「选择文件夹」同路径（即工作区选择器链路）；
拖放：带 File 的合成 drop 无异常、不劫持导航（OS 级 Explorer 拖入留人工）；关闭与状态恢复：窗口状态落盘 + 重开恢复 + N03 down/recover 循环验证。

#### F NSIS 安装测试 — BLOCKED（未执行，不模拟）

Windows Sandbox 不可用（`WindowsSandbox.exe` 缺失；`Get-WindowsOptionalFeature` 需提权，报错留档）；无独立测试 VM；
宿主机已安装 Tauri 版「Zhiyi AgentOS」（HKCU 卸载表项实证），直接试装违反并存隔离要求。
安装/升级覆盖/卸载三项**未验证**；win-unpacked 同二进制已运行验证（前次会话 CDP 取证）。

### 已知问题与环境限制（非阻断定性）

1. **验收会话上下文 console-ctrl 失效**：最小复现实验（`tmp/el01-signal-repro.py`）证明，从本会话（工具链后台 shell）以
   `CREATE_NEW_CONSOLE+SW_HIDE` 起的子进程收不到 `GenerateConsoleCtrlEvent` 的 CTRL_C（子进程日志无 KeyboardInterrupt）。
   影响面=`native.stop` 优雅停止在本上下文不可用；今早另一上下文的 `last-down.json` PASS 记录证明机制本身正常。
   处置=手工等价停止：Redis `shutdown(save=True)` 干净退出、PG `pg_ctl -m fast` rc=0、Electron 经 `close_desktop`（WM_CLOSE，
   窗口消息路径不受影响）、frontend/java/host/ai 经 `native.owned()` 四元组身份核实后树内终止——未杀任何未确认归属进程。
   该限制随验收环境消失，不构成产品缺陷；如需在本类上下文无人值守跑 down，后续可给 native_runtime 增加显式回退停止开关（本轮未改，遵守"仅最小修复"边界）。
2. Docker Desktop 在验收窗口内被外部反复启停（B 一轮中断根因），二轮已恢复并完成补验。
3. 桌面窗口为真实窗口，期间一次被外部关闭（主进程日志无错误、`window-all-closed` 正常退出路径），重拉后继续。

### 证据位置

- N02 一轮/二轮运行目录：`%LOCALAPPDATA%\Temp\kinlin-el01-n02-145300`、`kinlin-el01-n02b-183646`（各服务日志、`desktop-up.json`、down 记录）
- N03：`%LOCALAPPDATA%\ZhiyiNative\default\logs\last-down.json`（最终 PASS）、`backups\snapshot-el01-accept\`
- 驱动脚本（CDP 取证用，不入库）：worktree `tmp/el01-accept-{d,d2,d3,e,c2}.mjs`、`tmp/el01-dialog-probe.py`、`tmp/el01-signal-repro.py`、`tmp/el01-n03-manual-stop.py`
- 关键对象：`mission_957fde0ba20c` / `run_93c41ff86736`（N03 库内可查）

### 结论与放行条件

Electron 宿主在真实全栈（自建 jar + 原生 PG/Memurai + 真实模型执行 + 正式控制审批链）下完成了 Tauri 版已知的全部桌面侧职责，
无 P0/P1 发现，未对执行系统做任何修改。**CONDITIONAL ACCEPT**；默认入口切换待两件事放行：
① Windows Sandbox/测试机完成 NSIS 安装-升级-卸载实测（不影响已装 Tauri 版）；② OS 级拖放与 UI 级审批人工点验。

---

## 附录：来源清单与合并说明

| # | 原文件 | 日期 | 性质 | 原文大小 |
|---:|---|---|---|---:|
| 1 | `PR-EL-01-Electron桌面宿主迁移报告.md` | 2026-10-29 | 迁移报告 | 11281 字节 |
| 2 | `PR-EL-01-ACCEPTANCE-Electron桌面验收报告.md` | 2026-10-29 | 独立验收报告 | 8115 字节 |

> **合并规则**：正文逐字保留，仅做两类机械处理：(1) 标题层级下移一级，原文 H1 由本节标题替代；(2) 指向已合并 / 已归档文档的相对链接改写为新文件名。结论、数字、命令与代码块未改动。
>
> **完整性校验**：合并时对每篇原文做归一化比对（忽略标题层级与链接目标），本篇 2 篇全部一致。
>
> **恢复原件**：原文件已从当前目录移除，完整内容保留在 Git 历史中。整理提交前用 `git checkout HEAD -- "docs/开发记录/<原文件名>"`；提交后用 `git checkout HEAD~1 -- "docs/开发记录/<原文件名>"`。
