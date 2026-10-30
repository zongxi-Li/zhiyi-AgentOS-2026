# N03 Windows 无 Docker 持久开发环境

当前 Hands 动态工作区用法及真实 Electron 验收范围见
[EX-M1 运行说明](README-EX-M1.md) 和
[M2B 验收记录](../../../../../docs/开发记录/PR-EX-M1-M2B-执行闭环与工作区授权-合并记录.md)。
Hands 配置下，初始化工作区是启动默认值；用户可在桌面另选目录并由后端授权。
每个正式 Run 冻结授权身份，撤销后不能通过重新授权继承旧 Run 权限。
Python 依赖锁包含 WorkspaceAuthority 使用的 `psycopg[binary]`；首次安装仍使用下述带 hash 的锁文件。

使用真实 PostgreSQL、Memurai、Java、Python ExecutionRuntime、知行 Host 和 Electron 桌面壳。
本入口不调用 Docker，不创建系统服务，不修改系统 PATH 或防火墙。旧的容器部署资产已删除，
本入口是当前唯一的本地运行形态；数据迁移与回执见 `migrate_from_docker.py` 与批次迁移记录。

## 依赖准备（普通用户）

JDK 21、Maven、Node，以及现有前端 npm 依赖必须可用。还需 Electron 运行时
（`apps/desktop/electron` 的 npm 依赖；Electron 二进制经 npm 安装，网络受限时可设
`ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/`）。
Python 3.14 使用 N01A 的两份锁文件安装到固定用户目录，参见 [N01A README](README.md)。

```powershell
# 仓库根目录
python -m venv "$env:LOCALAPPDATA\ZhiyiNative\python"
$py = "$env:LOCALAPPDATA\ZhiyiNative\python\Scripts\python.exe"
& $py -m pip install --require-hashes --only-binary=:all: -r apps/agent/requirements.lock -r apps/agent/requirements.native-tools.lock
& $py -m pip check
& $py ops/scripts/infra/windows/native/prepare_persistent_dependencies.py
Push-Location apps/backend
mvn -DskipTests package
Pop-Location
```

依赖包位于 `%LOCALAPPDATA%\ZhiyiNative\dependencies`。脚本下载并校验固定包，
直接读取 MSI/CAB 解出 Memurai，**不执行 msiexec 安装**。PostgreSQL 为 EDB 的 15.19
Windows x64 ZIP；本脚本的 ZIP hash 是从供应商 HTTPS 下载后固定的摘要，并非独立签名。
Memurai 4.1.2 的 hash 来自微软 winget 清单，下载的 MSI 签名为 Janea Systems 且有效。
此固定版本实际兼容 Redis API 7.2.5；不宣称已覆盖 Redis 7.4 全部新特性。

**Memurai Developer 仅限开发测试，连续运行最多 10 天，另有连接来源和内存限制。**
当前环境是持久开发版；无限期连续生产运行需要合适的 Enterprise 授权及相应验证。
脚本不购买许可证、不绕过限制、不设周期重启规避限制。
参考：[下载与限制](https://www.memurai.com/get-memurai)、
[独立进程运行方式](https://docs.memurai.com/en/config-file)。

## 首次初始化和重复启停

```powershell
$entry = '.\ops\scripts\infra\windows\native\persistent.ps1'
$homeDir = "$env:LOCALAPPDATA\ZhiyiNative\default"
& $entry init -HomeDir $homeDir -Python $py
& $entry up -HomeDir $homeDir -Python $py -Desktop
& $entry status -HomeDir $homeDir -Python $py
& $entry down -HomeDir $homeDir -Python $py
# 下次直接复用同一 home；不要重新创建数据库或换密钥
& $entry up -HomeDir $homeDir -Python $py -Desktop
```

`init` 默认一次性从现有 `.secrets/kinlin-win-p1-001/deepseek_api_key` 读取模型密钥，
并复制到当前 Windows 用户的 DPAPI 密文。也可明确指定 `-ProviderKeyFile 'C:\私有路径\key.txt'`。
后续启动不依赖原密钥文件、容器或旧容器目录内容。
自选工作目录仅能在首次 init 指定 `-Workspace 'C:\明确授权目录'`；默认是 home 内的 workspace。
后续目录和 opaque Grant 身份保持固定，不能通过重复 init 扩张范围。

首次通过桌面注册/登录；Chat 顶部确认已有授权目录。写入/Patch 仍须系统审批。
Mission 仍按正式控制区执行：准备任务图 → 激活暂停 → 准备交接 → 申请执行许可 → 执行。
关闭后再次 up 可登录原账户，继续查看会话、Mission、Run 和 canonical final deliverable。

默认 loopback 端口：PostgreSQL 15432、Memurai 16379、Python 18761、知行 18765、
Java 18080、Vite 15200；`-Desktop` 使用 Chromium CDP 19222 开发取证端口。
成功 up/status/down 返回 0；DOWN 或冲突、初始化/恢复失败返回非零。
同一 home 的生命周期由 OS 文件锁串行化；已运行时再次 up 会拒绝，不会重复执行或换库。

## 数据和身份

| 路径/数据库 | 内容 |
| --- | --- |
| `environment.json` | 固定环境、数据库身份和工作区配置，无密码 |
| `credentials.dpapi` | PostgreSQL 管理员/应用密码、Redis 密码、JWT/内部令牌、HMAC、加密键及模型密钥；当前用户 DPAPI |
| `postgres\` | 独立 PostgreSQL cluster；固定 `zhiyi` 库、受限应用角色 `zhiyi_app` |
| `redis\` | Memurai RDB、AOF；DB 0 Java 缓存，1 Lua lease 协调，2 预留 provider state，3 验收探针 |
| `data\` | 现有生产 Runtime 的 SQLite、Checkpoint、Artifact 内容与 manifest 等 |
| `workspace\` | 默认系统签发 Grant 的文件根目录 |
| `uploads\` | Java 上传数据 |
| `webview\` | 历史 Tauri WebView 用户数据目录；Electron 壳不再使用，备份默认不含登录浏览器状态 |
| `electron\` | Electron 壳的 Chromium 用户数据与窗口状态；与桌面热更新链隔离，无业务数据 |
| `logs\<UTC时间>-<随机标识>\` | 每次进程启动日志及 up 记录，不覆盖以前的日志 |
| `logs\last-down.json` | 最近正常停止、端口、SQLite 独占句柄和 OS 锁检查结果 |

初始化收紧的是本环境新建目录 ACL，仅当前用户和 SYSTEM；没有放宽目录或执行器权限。
Redis 启动配置和 initdb 密码临时文件位于受限 temp，读取成功后删除；固定密码不放在
进程命令行。down 保留 DPAPI 文件和全部数据。
登录会话权威仍是 PostgreSQL 的 `iam_login_sessions`，不是 Memurai 中的新会话真源。

## 停止、故障恢复与冷备份

```powershell
# 需要从残留/部分运行状态恢复时，先按已记录身份正常停止，再用同一身份启动
& $entry recover -HomeDir $homeDir -Python $py -Desktop

# 一致性冷备份要求先完整停止；不会在线复制正在写入的数据库
& $entry down -HomeDir $homeDir -Python $py
$snapshot = "$env:LOCALAPPDATA\ZhiyiNative\backups\snapshot-$([guid]::NewGuid().ToString('N'))"
& $entry backup -HomeDir $homeDir -Python $py -Snapshot $snapshot

# 校验所有文件摘要和 DPAPI，再恢复到原 home 路径；保留整个现状为回滚副本
& $entry restore -HomeDir $homeDir -Python $py -Snapshot $snapshot
& $entry up -HomeDir $homeDir -Python $py -Desktop
```

冷备份包含 PostgreSQL cluster、Redis RDB/AOF、SQLite/Artifact、内部 workspace、
uploads、固定配置和 DPAPI 密文，生成逐文件 SHA-256。要求相同 Windows 用户/机器、
相同 PostgreSQL 主版本/二进制及原 home 路径，避免改写 Artifact 的绝对路径合同。
恢复保留 `default.pre-restore-<标识>` 目录，不删除现有数据；备份和回滚副本不会自动清理。
外部 `-Workspace` 不包含在 home 冷备份里，需独立备份，不能把配置恢复冒充外部文件恢复。
备份拒绝 reparse point；运行中不能执行 backup/restore。

端口被无关进程占用、记录 PID 身份不匹配或 schema 不兼容时保持失败，不强杀无关进程、
不删除锁文件绕过 OS 锁、不清空数据库。SQLite schema 复用正式准备工具：首次显式初始化，
后续先只读检查，不因重启而重建库。需要升级时先备份，再按准备工具的正式 apply 合同操作。

## 持久性探针（验收账户环境）

```powershell
& $py ops/scripts/infra/windows/native/persistent_checks.py --home $homeDir --output "$env:TEMP\redis-check.json"
# 若本地 DPAPI 已保存验收账户 JWT，可记录真实 Run 在重启前后的一致性
& $py ops/scripts/infra/windows/native/persistent_checks.py --home $homeDir --run-id '<真实RunId>' --output "$env:TEMP\state-check.json"
```

这些探针调用真实 Memurai 和生产 Lua coordinator / 正式 HTTP API；不能替代实际桌面
操作。本轮证据和剩余限制见 [N01A ~ N03 运行链合并记录](../../../../../docs/开发记录/PR-N01A-N03-Windows原生运行链-合并记录.md)。

## 桌面壳（Electron 单壳）

`persistent_runtime` 经 `desktop_shell.py` 拉起唯一的 Electron 壳：以
`node apps/desktop/electron/node_modules/electron/cli.js` 启动，`--dev-server`
指向本环境 Vite（`--mode electron`），CDP 调试端口为 19222 + 端口偏移，就绪探测为
`/json/version`，窗口类名 `Chrome_WidgetWin_1`（需先在 `apps/desktop/electron` 执行
`npm install`）。`KINLIN_DESKTOP_SHELL` 仅接受 `electron`（默认），设为其他值会启动即
报错；状态文件 `shell` 字段恒为 `electron`，历史状态仅作记录；`persistent.ps1` 不再有
`-Shell` 参数。数据库、工作区、`environment.json`/`credentials.dpapi` 身份与所有持久
数据完全不变；同一 home 重复 up/down/recover 亦不重建任何数据。
桌面壳的 Chromium 用户数据固定在 `home\electron\`（不再与桌面热更新链共用默认
`userData`，避免 Electron 单实例锁把 N03 窗口顶掉）；窗口位置状态随之独立，业务数据不受影响。
N02（旧桌面开发入口）已退役，本入口是唯一的原生桌面运行形态。
