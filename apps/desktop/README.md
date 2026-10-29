# 知弈 AgentOS 桌面版（Electron）

桌面版基于 Electron（Chromium）作为 Windows 桌面壳，把现有 Vue 前端打包为本地应用，
通过 HTTP、SSE 与 WebSocket 连接本机 Java 后端（原生 N03 栈，默认 18080）。
Electron 是当前唯一桌面宿主；Tauri 2 宿主已随桌面入口切换整体移除，迁移与验收过程见
`docs/开发记录/PR-EL-01 系列报告`。

- 宿主实现与开发/打包/安全基线说明：[electron/README.md](./electron/README.md)
- 开发热更新入口（桌面快捷方式同款）：`ops/scripts/start-desktop-hot.ps1`
- 原生持久环境（N03）经 `desktop_shell.py` 拉起同一 Electron 壳；N02 Docker 桌面入口已退役

桌面壳只负责窗口、原生交互与桌面生命周期；任务执行权威在 AgentOS Runtime 与
知行 Host，桌面端不内嵌执行器或调度器。
