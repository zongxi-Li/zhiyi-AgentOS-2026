# 知弈 AgentOS Electron 桌面宿主

Electron 版 Desktop Host。与 Tauri 版（`apps/desktop/src-tauri`）并存，共用同一套
`PlatformAdapter` 前端合同与原生生命周期；本包只负责窗口、原生交互与桌面生命周期，
不内嵌执行器、Scheduler 或模型调用——任务执行权威仍在 AgentOS Runtime 与知行 Host。

## 目录

- `src/main.ts` — 主进程：无边框窗口、安全加固、白名单 IPC、自定义协议、生命周期与日志
- `src/preload.ts` — 沙箱 Preload：`contextBridge` 暴露 `window.kinlinDesktop` 最小面
- `src/lib/` — 纯逻辑（IPC 通道合同、参数校验、窗口状态、CSP/协议资产、文件日志），node:test 单测在 `test/`
- `scripts/dev.mjs` — 开发编排（编译 → 起/复用 Vite → 起 Electron → 退出清理）
- `scripts/copy-renderer.mjs` — 打包前置：复制前端 Electron 产物与品牌图标
- `electron-builder.yml` — NSIS 打包配置（独立 appId `com.kinlin.zhiyi.electron`，与 Tauri 安装版并存互不影响）

## 开发

```powershell
# 首次
npm install   # 网络受限时先：$env:ELECTRON_MIRROR='https://npmmirror.com/mirrors/electron/'
# 前端依赖：apps/frontend 下 npm ci

# 热更新开发（15100 端口，退出自动清理 Vite）
npm run dev
# 或经仓库级入口（自动清残留进程/端口）：
powershell -File ops/scripts/start-desktop-electron.ps1

# 外部已有 dev server（例如 N02/N03 在 15200 起了自己的 Vite）时复用：
ELECTRON_DEV_SERVER_URL=http://127.0.0.1:15200 npm run dev
```

开发模式页面来自 Vite dev server（`--mode electron`），API/SSE/WS 走 Vite 代理；
生产模式从注册为 standard+secure 的自定义协议 `kinlin-app://shell` 加载 asar 内产物，
Origin 固定为 `kinlin-app://shell`（后端 CORS 已加该来源，不用通配符）。

## 构建 / 打包 / 测试

```powershell
npm test                # lib 纯逻辑单测（node --test，不需要 electron 二进制）
npm run build           # 仅编译 main/preload 到 dist/
# 前端产物：
cd ../../frontend && npm run build:electron   # 产物在 dist-electron/（不影响 Web 的 dist/）
cd ../desktop/electron
npm run pack            # 免安装目录（release/win-unpacked）
npm run dist            # NSIS 安装包（release/*-Setup.exe）
```

打包身份与 Tauri 版并存：appId/产品名/快捷方式均带 Electron 标识，
安装与卸载不会触碰已安装的 Tauri 版。验收通过前 Tauri 仍是默认入口
（`start-desktop-hot.ps1` 原样保留）。

## 安全基线

`contextIsolation: true`、`nodeIntegration: false`、渲染沙箱、权限请求全拒、
`will-navigate`/`window.open` 白名单、webview 附加拒绝、协议路径穿越防护、
生产 CSP（无 `unsafe-eval`、无通配符来源）。IPC 逐通道校验 sender 与参数
（见 `src/lib/validation.ts` 与 `test/`）。

## 回退

Electron 验收不通过时：Tauri 入口（`start-desktop-hot.ps1`、`desktop.ps1 -Shell tauri`）
与所有原构建命令未做任何改动，直接使用即可；如需彻底移除，删除本目录与
`ops/scripts/start-desktop-electron.ps1` 即可，无共享文件残留。
