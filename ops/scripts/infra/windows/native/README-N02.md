# N02 Windows 原生桌面开发入口

在仓库根目录运行。复用 N01A 的 Python 环境和生产 Runtime，详见
[N01A 依赖准备](README.md)。本入口不会运行 N01A symlink 验收。

## 前提

- Windows 11，JDK 21、Maven、Node、已安装的前端 npm 依赖，以及 Electron 运行时
  （`apps/desktop/electron` 的 npm 依赖；Electron 二进制经 npm 安装，网络受限时可设
  `ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/`）。
- N01A 锁文件安装的 Python 3.14 环境（包括 pywin32、psutil、redis）。
- 已运行的 `kinlin-win-p1-001-postgres-1`、`kinlin-win-p1-001-redis-1`。
  PostgreSQL 容器内须有 BusyBox `nc`，并可通过 `redis:6379` 访问 Redis。
- `.secrets/kinlin-win-p1-001/deepseek_api_key` 和 `redis_password` 存在且有效。
  不要把这些文件内容放进命令行、Git 或报告。
- 18761、18765、18080、15200、15432、16379，以及桌面调试端口 19222 空闲。

## 构建和启停

```powershell
Push-Location apps/backend
mvn -DskipTests package
Pop-Location
$py = "$env:TEMP\kinlin-n01a-20261028\venv\Scripts\python.exe"
$entry = '.\ops\scripts\infra\windows\native\desktop.ps1'
$run = "$env:TEMP\kinlin-n02-$([guid]::NewGuid().ToString('N'))"
& $entry up -RunDir $run -Python $py -Desktop
& $entry status -RunDir $run -Python $py
& $entry down -RunDir $run -Python $py
```

默认新建 `$run\workspace`。使用现有真实目录时，在 `up` 增加
`-Workspace 'C:\你的工作目录'`；这表示明确授权本次 Host Grant 的根目录。
服务启动后，在 Chat 顶部通过 Windows 原生选择器确认同一目录。选择其他目录会被拒绝，
须停止服务并指定新的 `-Workspace` 重启。界面选择不会扩张 Grant。
当前是单用户、单个启动工作区的开发接线，不提供动态跨目录授权管理。

每次 `up` 使用不存在的独立 `$run`，创建新的 PostgreSQL 数据库/角色、空闲 Redis DB
和独立 SQLite。旧运行目录不能被 `up` 覆盖；这不是持久用户安装版的重启入口。
首次通过桌面正常注册和登录测试账户；创建 Mission 后，按正式控制区依次准备任务图、
激活暂停、准备交接、申请许可、执行，最终在 OUTPUT 打开 `final.md`。
Chat 文件写入和 Patch 仍须确认系统审批。ACG 的能力范围保持既有绑定，不自动获得 Chat 写工具。

`up/status/down` 成功退出 0；状态 DOWN 或启动/停止错误返回非零。
`up` 等待三个原生服务及前端就绪；`-Desktop` 额外构建并打开真实 Electron 窗口。
它复用同一个桌面运行时入口。19222 仅是本机开发调试端口，不应出现在发布安装版。

PostgreSQL/Redis 使用绑定 127.0.0.1 的 stdio 开发转发：`docker exec -i ... nc`。
保留 PostgreSQL/Redis 自身认证及 JWT、内部令牌和 Host HMAC；未发布数据库端口，未修改容器配置。
Java 运行正式 PostgreSQL/Flyway 配置，前端 API/SSE 经本机 Vite 转发到 Java。
`/ai` 的 WebSocket Upgrade 也保留 Java 边界，但现有 Java 没有语音 WS 桥接端点，
实时语音未完成验收；不能直连 Python 来绕过鉴权。
Docker 中原有 backend/ai/frontend 可以保留运行，但本链路不访问它们。

`down` 仅停止记录且身份匹配的进程树，关闭属于本次启动的 Electron 窗口，验证端口、
SQLite 独占句柄、OS 锁释放并删除 DPAPI 临时凭据。日志和测试数据保留供检查，
不会 DROP DATABASE、删除角色、FLUSH Redis 或删除原环境数据。留存的测试数据库/角色
需另行明确授权后清理；不要对旧业务库使用清理命令。

## 桌面壳（Electron 单壳）

`desktop_runtime` 经 `desktop_shell.py` 拉起 Electron 桌面壳：以
`node apps/desktop/electron/node_modules/electron/cli.js` 启动，`--dev-server`
指向本环境的 Vite 开发服务器（`--mode electron`，同一 15200 端口、代理与就绪等待不变），
并暴露 Chromium CDP 调试端口（19222 + 端口偏移），就绪探测为 `/json/version`，
窗口类名为 `Chrome_WidgetWin_1`，`show/close` 仍只作用于本次生命周期的进程树。

`KINLIN_DESKTOP_SHELL` 环境变量仅接受 `electron`（默认值）；设为其他值（如 `tauri`）
会启动即报错。状态文件的 `shell` 字段恒为 `electron`；旧运行目录里的历史状态仅作记录，
不再复用。`desktop.ps1` 不再有 `-Shell` 参数。进程身份校验、端口检查、资源释放与
停止语义均不变。

验收与已知限制见 [N02 实施报告](../../../../../docs/开发记录/PR-N02-Windows-Native-Desktop-实施与验收.md)。
