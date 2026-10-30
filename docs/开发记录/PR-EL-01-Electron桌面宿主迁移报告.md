# PR-EL-01 Electron 桌面宿主全链路迁移报告

> 本文保留 EL-01 历史迁移验收范围，不代表动态工作区和 Hands 正式开发已经验收。
> 后续基于主仓当前代码的 Electron + WorkspaceAuthority + ACG/Hands 联调、回归及剩余问题见
> [PR-EX-M2B 验收记录](PR-EX-M2B-动态工作区ACG-Hands端到端验收.md)。

日期：2026-10-29　分支：`pr-el-01-electron-host`（独立 worktree `../kinlin_ai-el01`，基于 master `145726f0`）

## 结论

Electron 桌面宿主已落地并可开发、可运行、可打包、可连接现有 Runtime：开发模式与打包版均在本机
真机打开过窗口并经 CDP 取证；窗口三键、F11、最大化状态同步、状态持久化、Preload 白名单桥、
渲染沙箱、外链协议校验全部实测通过。Web/Tauri 构建模式零破坏（全量前端回归 729/729、Web 构建通过）。
Tauri 入口原样保留为回退路径。执行系统（另一合并任务）的合同、调度、审批、Attempt Fence、
Checkpoint、GraphVersion、Workspace Grant 一律未触碰。

## 基线

- 起点：master `145726f0`；工作区未提交改动（执行系统合并任务的 12 M + 8 ?? 文件）原样保留在主工作区，未读取、未修改。
- 本任务全部改动发生在独立 worktree/分支，无 push、无 merge。
- 工具链：Node 24.19.0、Electron 45.1.0（Chromium 156.0.8078.49）、electron-builder 26.18.0、esbuild 0.28.2。

## 架构决策

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

## 文件变更

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

## 测试与验证结果

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

## 未验证项（明确登记，不以模拟充数）

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

## 已知问题

- 未配置代码签名证书（Tauri 版同样未签）；SmartScreen 可能提示，属既有基线。
- CSP 未含 `unsafe-eval`：若后续引入需要 eval 的依赖需重估（当前全量页面在打包版正常加载）。
- Electron dev 与 Tauri dev 共用 15100，二者不可同时跑（strictPort 快速失败，防静默漂移）。
- `window.kinlinDesktop` 的 Renderer 类型（bridge.ts）与 Preload 实现手工同构，改动需双侧同步
  （ipc-contract.ts 注释已标注）。

## 与执行系统合并任务的冲突点

- 主工作区未提交改动涉及的文件中，`ops/scripts/infra/windows/native/{persistent.ps1,persistent_runtime.py,native_runtime.py}`
  与本任务改动的同名文件在 worktree 基于 HEAD 修改。合并时预期冲突点：
  `persistent_runtime.py` 的 `up()` 桌面段与 CORS 行、`persistent.ps1` 参数块。解法：本任务的改动
  是把桌面段收敛为 `desktop_shell` 调用，语义包含旧逻辑，按本任务形态解冲突并保留对方执行系统的
  其他修改即可；`native_runtime.py` 本任务未改。
- `apps/frontend/src/plugins/index.ts`、`components/workspace/*` 等对方改动文件本任务均未触碰。
- CORS/白名单与应用层执行合同正交，无语义冲突。

## 残余 Tauri 依赖与回退说明

- Tauri 工程与入口完整保留：`apps/desktop/src-tauri/`、`start-desktop-hot.ps1`、`start-desktop-built.ps1`、
  `dev-hot-reload.bat`、`desktop.ps1 -Shell tauri`（默认值即 tauri）、`npm run dev:desktop`/`build:desktop`。
- 生产 backend/网关的 `tauri://localhost`、`http://tauri.localhost` 来源仍保留在白名单。
- Electron 验收通过前，桌面默认入口不变；要回退：不使用 Electron 入口即可，如需彻底移除，
  删除 `apps/desktop/electron/` 与 `ops/scripts/start-desktop-electron.ps1`，无共享文件残留
  （vite.config 的 electron 分支在 mode!=electron 时不生效）。
- 待 Electron 全量验收后再切换默认入口（届时单独一笔提交改 start-desktop 脚本指向）。
