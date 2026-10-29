# PR-EL-01-ACCEPTANCE Electron 全栈验收报告

日期：2026-10-29　分支：`pr-el-01-electron-host`（worktree `kinlin_ai-el01`，无新增功能改动）
前置：PR-EL-01 迁移六笔提交 `79ce3e85..1f9f33f8` 原样保留，未 push、未 merge、未切默认入口。

## 终判：CONDITIONAL ACCEPT

核心迁移准入项（N02 全栈、N03 持久环境、真实业务链路、原生交互、窗口控制）全部通过或经等价路径验证；
存在两项明确的非阻断限制（F 安装实测 BLOCKED、验收会话上下文的 console-ctrl 环境限制）。
**默认桌面入口切换建议暂缓**：待 NSIS 安装实测（需 Windows Sandbox/测试机）与 OS 级拖放人工点验后一并放行。

## 逐项结果

### A 自动化测试与构建复核 — 通过

| 项 | 命令 | 结果 |
| --- | --- | --- |
| 前端全量 | `npm test`（apps/frontend） | 108 文件 / 729 例全过（123.6s） |
| Electron lib | `npm test`（apps/desktop/electron） | 13/13 |
| Native 抽象 | `pytest ops/scripts/infra/tests/test_desktop_shell.py` | 15/15 |
| 架构门禁 | `pytest apps/agentOS/tests/architecture/test_capability_upgrade_gates.py` | 16/16 |
| 后端 jar | `mvn -DskipTests package`（worktree） | 79,082,502B 成品 |
| Web/Electron 构建 | `npm run build:web` / `build:electron` | 均通过（前次会话，产物未变） |

### B N02 Electron 全栈 — 通过（含一次外部环境中断取证）

一轮：`desktop.ps1 up -Desktop -Shell electron` → `status=UP`、`desktopShell=electron`、独立库 `n02_0c5c14ac23`、
Electron 窗口（CDP 19222，`登录 - 知弈AgentOS`）。期间 **Docker Desktop 被外部整体退出**（时间线：容器 14:44 全停 → 14:47 全起 → ~14:57 Docker 退出；docker pipe 不存在实证），`docker exec nc` 转发链断 → Java 报 `SQLState 08001 / HikariPool 超时`。该中断非 Electron/桌面壳缺陷。down 两段式：首跑六服务优雅停止超时登记（`desktop-down-errors.json`），进程随后自行退出；二跑正式 **PASS**（端口释放、SQLite 独占句柄核验、临时凭据清除、测试库保留）。

二轮（Docker 恢复后）：up → UP → 注册/登录/工作区绑定 200/200/200（docker relay 链 + Electron 窗口）→ down 两段式 → **PASS**，端口全释放。

### C N03 持久环境 — 通过（身份/数据零变更）

- 状态检查：干净停止态（owned 进程全缺失），`environment.json`/`credentials.dpapi` 身份校验通过。
- 冷备份：`persistent.ps1 backup` → **PASS**（`snapshot-el01-accept`，1372 文件 + 逐文件 SHA-256）。
- `up -Desktop -Shell electron` → UP（Electron 窗口 + 全部原生服务）。
- `recover -Desktop -Shell electron` → exit 0，同身份重启（恢复能力 + 重复启动）。
- 数据持久性（重启后经窗口实测）：同账号登录 200 且 userId 一致；Mission 列表含本验收任务；
  Run `run_93c41ff86736` 保持 `completed`/2 outputs/`formalControl=ACTIVATED`。**未重建数据库、未轮换密钥、未清业务数据**（`persistentCredentialsRetained=true`）。
- 最终 down **PASS**（processesAbsent/portsReleased/databaseHandlesReleased/workflowLockReleased 全 true）。

### D 真实业务链路 — 通过（经 Electron 渲染进程，N03 真实栈）

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

### E 窗口与原生交互 — 通过

三键：toggleMaximize false→true→false、minimize 后 Win32 `IsIconic=True`（类名 `Chrome_WidgetWin_1`）、close 干净退出；
F11 全屏往返 true→false；缩放：视口 1456→1011 比值 **1.44（=1.2² 两档）**、Ctrl+0 复位精确回 1456；
原生文件对话框：IPC → Win32「打开」(#32770) → 取消 → null；原生目录对话框：「选择文件夹」同路径（即工作区选择器链路）；
拖放：带 File 的合成 drop 无异常、不劫持导航（OS 级 Explorer 拖入留人工）；关闭与状态恢复：窗口状态落盘 + 重开恢复 + N03 down/recover 循环验证。

### F NSIS 安装测试 — BLOCKED（未执行，不模拟）

Windows Sandbox 不可用（`WindowsSandbox.exe` 缺失；`Get-WindowsOptionalFeature` 需提权，报错留档）；无独立测试 VM；
宿主机已安装 Tauri 版「Zhiyi AgentOS」（HKCU 卸载表项实证），直接试装违反并存隔离要求。
安装/升级覆盖/卸载三项**未验证**；win-unpacked 同二进制已运行验证（前次会话 CDP 取证）。

## 已知问题与环境限制（非阻断定性）

1. **验收会话上下文 console-ctrl 失效**：最小复现实验（`tmp/el01-signal-repro.py`）证明，从本会话（工具链后台 shell）以
   `CREATE_NEW_CONSOLE+SW_HIDE` 起的子进程收不到 `GenerateConsoleCtrlEvent` 的 CTRL_C（子进程日志无 KeyboardInterrupt）。
   影响面=`native.stop` 优雅停止在本上下文不可用；今早另一上下文的 `last-down.json` PASS 记录证明机制本身正常。
   处置=手工等价停止：Redis `shutdown(save=True)` 干净退出、PG `pg_ctl -m fast` rc=0、Electron 经 `close_desktop`（WM_CLOSE，
   窗口消息路径不受影响）、frontend/java/host/ai 经 `native.owned()` 四元组身份核实后树内终止——未杀任何未确认归属进程。
   该限制随验收环境消失，不构成产品缺陷；如需在本类上下文无人值守跑 down，后续可给 native_runtime 增加显式回退停止开关（本轮未改，遵守"仅最小修复"边界）。
2. Docker Desktop 在验收窗口内被外部反复启停（B 一轮中断根因），二轮已恢复并完成补验。
3. 桌面窗口为真实窗口，期间一次被外部关闭（主进程日志无错误、`window-all-closed` 正常退出路径），重拉后继续。

## 证据位置

- N02 一轮/二轮运行目录：`%LOCALAPPDATA%\Temp\kinlin-el01-n02-145300`、`kinlin-el01-n02b-183646`（各服务日志、`desktop-up.json`、down 记录）
- N03：`%LOCALAPPDATA%\ZhiyiNative\default\logs\last-down.json`（最终 PASS）、`backups\snapshot-el01-accept\`
- 驱动脚本（CDP 取证用，不入库）：worktree `tmp/el01-accept-{d,d2,d3,e,c2}.mjs`、`tmp/el01-dialog-probe.py`、`tmp/el01-signal-repro.py`、`tmp/el01-n03-manual-stop.py`
- 关键对象：`mission_957fde0ba20c` / `run_93c41ff86736`（N03 库内可查）

## 结论与放行条件

Electron 宿主在真实全栈（自建 jar + 原生 PG/Memurai + 真实模型执行 + 正式控制审批链）下完成了 Tauri 版已知的全部桌面侧职责，
无 P0/P1 发现，未对执行系统做任何修改。**CONDITIONAL ACCEPT**；默认入口切换待两件事放行：
① Windows Sandbox/测试机完成 NSIS 安装-升级-卸载实测（不影响已装 Tauri 版）；② OS 级拖放与 UI 级审批人工点验。
