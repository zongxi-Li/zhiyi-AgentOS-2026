# 内置本地终端：实施与验收

2026-10-30，Windows 本机 Electron + N03 环境。

## 已实现

- 全局底部终端面板：顶部入口、Ctrl+反引号开关、多标签、关闭单标签、清空显示、Shell 选择、任意目录选择与可拖动高度。
- xterm + 独立 node-pty Host 的真实 PTY；本机发现 PowerShell 7、Windows PowerShell、CMD、Git Bash。
- 新建终端优先取当前业务工作区，目录状态栏明确表示“启动目录”；后续 `cd` 由 Shell 提示符反映。
- 折叠、切页、刷新保留会话 PID、工作目录与变量；关闭单个标签只回收该标签。正常退出 Electron 回收本次桌面所属 PTY 与前台子进程。
- N03 自动启动、记录并停止终端服务；已有健康环境可通过 `open` 补启，保持数据库与其他服务进程。
- Main IPC 仅接受主窗口主框架，专用凭据不暴露给 renderer；所有者隔离，Shell 环境变量过滤，输入/尺寸/输出缓冲上限。
- xterm 懒加载。生产构建不再与正在运行的 Vite 同时写生成声明，解决 Windows 文件竞争。

## 实际验收

实际 Electron CDP 页面经 Playwright 操作，不调用模型、不生成业务 Run。写入位置为操作系统临时目录，未向用户桌面写验收文件。

| 检查 | 结果与证据 |
| --- | --- |
| 中文输入、HTML 写入与读取 | `PTY_UI_OK42` 和 `<h1>知弈终端中文</h1>` 实际输出 |
| 目录、变量保留 | `cd` 后相对写入成功；折叠/重开后输出 `STATE74` |
| Python REPL | `python -q` 中 `sum([19,23])` 输出 `REPL_RESULT 42` |
| Ctrl+C | 中断前台 Node 常驻程序，回到 PowerShell，随后输出 `INTERRUPT_42` |
| 多标签 | 新建 CMD、输出 COMSPEC；关闭 CMD 后原 PowerShell 输出 `FINAL_74` |
| 切页与刷新 | 同一 session/PID 保留，刷新后变量输出 `RELOADED_74` |
| 退出与重开 | Shell PID 40444、前台 Node PID 12040 均回收；旧会话不复用，重新显示 PowerShell 提示符 |
| 后台保持 | postgres、redis、AI、Host、Java、Vite、terminal 服务身份全部保持；重开后状态 UP |

有效浏览器脚本使用输出游标与显式轮询等待新输出，避免把历史输出或尚未完成的异步检查误算为成功。最终证据：

- [真实交互截图](../../output/playwright/terminal-powershell-acceptance.png)
- [页面刷新后截图](../../output/playwright/terminal-reload-acceptance.png)
- [当前待人工验收界面](../../output/playwright/terminal-ready-for-user.png)
- [浏览器交互记录](../../tmp/terminal-browser-acceptance.log)
- [页面持久性记录](../../tmp/terminal-persistence-acceptance.log)
- [进程回收与重开回执](../../tmp/terminal-lifecycle-acceptance.json)

上述 output/tmp 文件为本机验收产物，不随 Git 自动纳入交付。

## 自动检查

| 检查 | 结果 |
| --- | --- |
| 前端全量 Vitest | 111 文件，743 测试通过 |
| Electron 测试 | 16 通过，包含 Main 传输凭据与 owner 隔离 |
| Terminal Host | 4 通过，包含真实 ConPTY、文件写入、Ctrl+C、进程回收 |
| N03 open/终端服务与架构守卫 | 21 通过 |
| 原生基础设施全量测试 | 38 通过 |
| Electron TypeScript | 通过 |
| 前端 electron / web 生产构建 | 均通过 |
| Git whitespace 检查 | 通过；有仓库既存 CRLF 转换提示 |

日志：`tmp/terminal-frontend-tests.log`、`terminal-electron-tests.log`、`terminal-host-test.log`、
`terminal-python-tests.log`、`terminal-electron-typecheck.log`、`terminal-frontend-build.log`、`terminal-web-build.log`。

## 边界与使用

点击“终端”或 Ctrl+反引号即可使用。供人操作的 Shell 使用当前 Windows 用户权限，命令取决于本机安装与 PATH。
本次没有把终端接入模型工具，也没有改变 Agent/Chat 的执行授权合同。终端会话不跨整个桌面重启恢复。
退出 Electron 保留后台；完整停止继续使用 N03 `down`。首次部署额外执行 `apps/terminal-host` 下的 `npm ci`。

node-pty 系统 ConPTY 的退出辅助进程偶尔记录 `AttachConsole failed`，已保留原始日志。
本轮真实 Shell 和前台子进程均确认回收；这不等于所有异常崩溃、系统断电或其他机器环境已验收。
未执行提交或推送，保留本轮之前的工作区/审批修复与其他改动。
