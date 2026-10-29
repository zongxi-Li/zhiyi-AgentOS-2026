# PR-N01A Windows 原生 Runtime 实施与验收

> 最新补充结论见第 8 节 PR-N01A-R1：**仍为 BLOCKED**。第 1～7 节保留首次实施记录；其中“BLOCKED 退出码未实测”的历史限制已由 R1 的真实 exit 2 证据关闭，symlink 夹具与真实全 PASS / exit 0 仍未满足。

日期：2026-10-28（Asia/Shanghai）。最终判定：**BLOCKED，不能标记 ACCEPT**。

**Python ExecutionRuntime 与知行 Local Runtime 的无 Docker AI 容器依赖最小文件链路已经在真实 Windows 上跑通。** 两个生产入口原生启动，真实生产装配的 `LocalRuntimeClient → HttpLocalRuntimeTransport → HMAC HTTP → Host` 完成 list/read/write/patch，并从磁盘独立复核内容和 SHA-256。但 N01A-06 的 symlink 子项因当前 Windows 令牌权限受阻，12 项未全部通过。本轮不进入 N01B。

## 1. 进入基线与保护范围

实施规范为 Downloads 中的 `PR-N01A-Windows-Native-Runtime-实施任务.md`，读取后以真实代码和现场结果重新判断。

- 分支 `master`，进入时 HEAD：`8b792fa0c2c422ed7548330ae3f1ea5bbf50883d`。
- 进入时已有 21 个 tracked 文件修改，涉及后端会话重检/流持久化、前端 Chat/SSE/Workbench/ACG；另有 `apps/frontend/src/stores/chat.stream.spec.ts` 和既有 Chat 修复记录两个 untracked 文件。完整列表见 [git-before.txt](../../artifacts/windows/native-n01a/20261028/git-before.txt)。本轮没有编辑这些文件。
- 进入/结束的原有 `git diff --binary` 内容一致，SHA-256 均为 `3f3e17ea65fa9165288aeeaea33e0c29fd84fd0479d64fd8ff09995f2f6ac8e5`。索引差异均为空。本轮没有 add、commit、push、reset、stash 或清理历史数据。
- 现有五个 Docker 服务（AI、Java、前端、PostgreSQL、Redis）一直保留运行。原有 Docker AI 的存在不构成本轮 Native 链路依赖：Native 未使用它的入口、挂载、数据库、令牌或模型配置，也没有新建 Docker AI 容器。
- [前后隔离/保护比较](../../artifacts/windows/native-n01a/20261028/isolation-and-preservation.json)；[实际成功启动的进程树](../../artifacts/windows/native-n01a/20261028/run-03/up.json)。

## 2. 真实源码检查与实现

实际阅读了任务要求列出的 Host main/bootstrap/grants/filesystem/http_server、AI main/wiring/instance_lock/tools runtime、AgentOS HTTP transport、两份依赖锁、prepare 脚本和 compose。确认既有生产代码已具备 HMAC、nonce 防重放、系统签发 Grant、canonical/reparse containment、文件原子写、Windows OS workflow 锁和正常退出清理；本轮复用这些实现，没有建立平行 Runtime。

本轮新增文件（原有业务源码、Compose 和两个原始锁未修改）：

| 文件 | 具体用途 |
|---|---|
| [requirements.native-tools.lock](../../apps/agent/requirements.native-tools.lock) | 独立 Windows 工具锁，保留原工具精确版本与原 hash，补齐 Windows wheel hash、colorama、pywin32 |
| [native.ps1](../../ops/scripts/infra/windows/native/native.ps1) | PowerShell 统一 preflight/up/status/down/smoke 入口 |
| [native_runtime.py](../../ops/scripts/infra/windows/native/native_runtime.py) | 路径/版本/端口门禁、专用配置、新库显式准备、两服务生命周期、PID 身份及进程树/端口/健康核验、正常停止与失败回收 |
| [smoke.py](../../ops/scripts/infra/windows/native/smoke.py) | 真实 app.main 装配、文件链路、磁盘复核、HMAC/授权/越界负例和第二 Uvicorn 争锁 |
| [verify_lifecycle.py](../../ops/scripts/infra/windows/native/verify_lifecycle.py) | 真 Host 已健康、AI 尚未启动时注入失败，验证回收与原服务不受影响 |
| [audit_secrets.py](../../ops/scripts/infra/windows/native/audit_secrets.py) | 检查本轮已知随机密钥在日志/回执/新增源码/索引中的泄露情况，不输出密钥值 |
| [refresh_tool_lock.py](../../ops/scripts/infra/windows/native/refresh_tool_lock.py) | 固定版本的 Windows hash 锁维护入口，TLS 读取 PyPI release JSON，pip 再校验真实 artifact bytes |
| [README.md](../../ops/scripts/infra/windows/native/README.md) | 安装、生命周期、复现、隔离及验收边界说明 |
| 本报告 | 逐项结果、证据与下一阶段必要条件 |

没有改动 ACG NodeRunner、Execution Permit、Review、Chat 审批或 Host 授权机制。Native 配置显式启用既有 Semantic/C2/Dispatch 三个开关；测试文件操作通过 Runtime 已装配的底层 LocalRuntimeClient，不向 ACG 注入可写 Chat 工具。

## 3. Windows 依赖实测

现场：Windows 11 `10.0.26100`，AMD64，CPython **3.14.5 / MSC 1944 / 64 bit**。基础解释器：`C:\Users\LZX\AppData\Local\Programs\Python\Python314\python.exe`。没有改用 3.11/3.13 规避安装问题。

专用虚拟环境：`C:\Users\LZX\AppData\Local\Temp\kinlin-n01a-20261028\venv`，`include-system-site-packages=false`。本机原有全局包版本与锁不同，未作为正式验收环境。

实测过程与根因：

1. 主锁 `requirements.lock` 的 Windows `--dry-run --ignore-installed --only-binary=:all: --require-hashes` 成功，生成 [解析回执](../../artifacts/windows/native-n01a/20261028/dependencies-main.json)。未出现需要本机源码构建的最终依赖；包括 numpy、onnxruntime、pandas、PyMuPDF 等均取得可用 Windows wheel。
2. 原 `requirements.tools.lock` 明确只锁 Linux wheel。实测 `cffi==2.1.0` Windows cp314 wheel 被拒绝：原期望 hash `d53d10f7da99ae46f7373b9150393e9c5eab9b224909982b43832668de4779f5`，下载 wheel hash `1b96bfe2c4bd825681b7d311ad6d9b7280a091f43e8f63da5729638083cd3bfb`。这是平台 artifact 不同，不能删除 hash 来安装。见 [原始失败日志](../../artifacts/windows/native-n01a/20261028/dependencies-tools.log)。
3. 新增独立 Windows 工具锁，保留所有原精确版本和原 hash，加入 PyPI 发布的 Windows/universal wheel hash。补齐 Click 的 Windows `colorama==0.4.6`；pip 随后指出 MCP 的 Windows 条件依赖 `pywin32>=311` 未固定，独立锁补入本次解析出的 `pywin32==312`，并校验 wheel hash。原 Linux 工具锁不变。
4. 锁维护时发生过 TLS EOF，保留原锁后重试；没有关闭 TLS 校验或配置 trusted-host。第一次/补齐过程失败日志保留，最终安装使用下面命令，成功且 `pip check` 无冲突。

```powershell
$base = "$env:TEMP\kinlin-n01a-20261028"
python -m venv "$base\venv"
$py = "$base\venv\Scripts\python.exe"
& $py -m pip install --require-hashes --only-binary=:all: `
  -r apps/agent/requirements.lock -r apps/agent/requirements.native-tools.lock `
  --report "$base\installed.json"
& $py -m pip check
```

[最终安装日志](../../artifacts/windows/native-n01a/20261028/install-complete.log)、[实际安装包与 artifact/hash 回执](../../artifacts/windows/native-n01a/20261028/installed.json)。测试专用 pytest 8.4.2 / pytest-asyncio 1.2.0 另装在同一隔离 venv，[测试依赖安装回执](../../artifacts/windows/native-n01a/20261028/test-dependencies.json)，随后 `pip check` 再次通过。没有放宽应用锁定版本。

## 4. 启动配置、命令与真实进程

成功 run：`C:\Users\LZX\AppData\Local\Temp\kinlin-n01a-20261028\run-03`。所有 Native 测试数据独立，未初始化仓库默认 data 或 Docker 卷。

| 配置/资源 | 本轮值或语义 |
|---|---|
| Python `APP_DATA_DIR` | 由 `AGENTOS_DATA_DIR=<run>\data` 决定；不是名为 APP_DATA_DIR 的环境变量 |
| Workflow / Checkpoint / Identity | `<run>\data\workflows.sqlite3` / `checkpoints.sqlite3` / `identity.sqlite3` |
| 其他 SQLite | 显式设置 EXECUTION_VALUE、CONTENT_MANIFEST、EXECUTION_MEMORY、PROVENANCE、AUDIT、RESOURCE、NODE、RESOURCE_HEALTH、EVOLUTION 各 AGENTOS_*_DB，均为 `<run>\data` 下绝对路径 |
| smoke 装配数据库 | `<run>\smoke-data-807e818f\`，与在线 AI 的数据库独立；每次 smoke 创建新库 |
| 附件 / Chroma / 缓存 | 各 data 目录下 attachments/chroma/cache；现有部分服务的相对 data 路径也因 cwd 为新 run 而隔离 |
| SQLite 临时文件 / TEMP / TMP | `<run>\temp` |
| Packs | `C:\Users\LZX\Desktop\kinlin_ai\apps\agent\packs`，只读发现真实 packs |
| PYTHONPATH | 仓库 apps、apps/agent、apps/agentOS、apps/agentOS/src 四个绝对路径 |
| Local Runtime | `127.0.0.1:18765`；资源 n01a-host、workspace n01a-workspace、grant n01a-grant、credential ID n01a-credential |
| 能力 | 仅 fs.list/read/write/patch，shell.exec 未启用 |
| AI | `127.0.0.1:18761`，workers=1，无 reload |
| Semantic/C2/Dispatch | 均 true；先只读检查，再通过现有 prepare 脚本显式初始化本轮新库并再次只读确认 READY |
| Provider / Redis / PostgreSQL | PROVIDER_STATE_ENABLED=false，不继承 coordination/provider Redis URL 或数据库地址、模型 API keys |
| 秘密 | 仅变量名：AI_INTERNAL_TOKEN、AGENTOS_RESOURCE_CREDENTIAL_KEY、AGENTOS_LOCAL_RUNTIME_CREDENTIAL_SECRET、ZHIYI_LOCAL_RUNTIME_CREDENTIAL_SECRET；随机生成，资源密钥为有效 Fernet key，Host/client HMAC 一致；DPAPI 当前用户加密落盘，正常停止后删除 |
| `.env` | run-local 空文件阻止既有配置加载器回退仓库 .env；不修改原配置加载机制 |

真实命令由隔离环境和 cwd 启动：

```text
<venv>\Scripts\python.exe -m runtime.main
<venv>\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 18761 --workers 1
<venv>\Scripts\python.exe <repo>\scripts\prepare_agentos_runtime.py
<venv>\Scripts\python.exe <repo>\scripts\prepare_agentos_runtime.py --apply --initialize-empty
<venv>\Scripts\python.exe <repo>\scripts\prepare_agentos_runtime.py
```

成功进程树：Host venv launcher PID **45440** → 基础 Python **5744**，AI launcher **41456** → 基础 Python **25880**；各有独立隐藏 conhost。Windows venv 的 launcher/解释器子进程是同一服务树，不是多 worker 或平行 Runtime。状态检测核验真实树内 socket 的 loopback 地址和端口，而非仅凭父 PID。完整 executable、命令和创建时间见 [up.json](../../artifacts/windows/native-n01a/20261028/run-03/up.json)。

保留的中间失败：run-01 因新 launcher 漏配 apps/agentOS 路径，AI import `service` 失败；run-02 两服务实际健康，但旧状态检测只检查 venv 父 PID，误判无监听并正常回收。补齐路径、树级监听检测后 run-03 通过。原日志未删，未通过改门禁解决。见 [run-01](../../artifacts/windows/native-n01a/20261028/run-01/ai.log)、[run-02 误判回执](../../artifacts/windows/native-n01a/20261028/run-02/up-failure.json)。

## 5. 12 项验收

下表的 PASS 只覆盖写明的实测范围；symlink 阻断不由 junction 或 pytest skip 替代。

| 编号 | 判定 | 实测观察与证据 |
|---|---|---|
| N01A-01 | **PASS** | 两个生产服务树均为 Windows .exe，启动新目录，无新 Docker AI 容器；[进程树](../../artifacts/windows/native-n01a/20261028/run-03/up.json)、[Docker 前后](../../artifacts/windows/native-n01a/20261028/isolation-and-preservation.json) |
| N01A-02 | **PASS** | /health/ready：status=UP；dataDirectory/workflowStore/packsRegistered 全 true；[原始 JSON](../../artifacts/windows/native-n01a/20261028/run-03/up.json)。/health/dependencies=DEGRADED，modelProvider=UNCONFIGURED，providerConversationState=DISABLED，不误报生产依赖可用 |
| N01A-03 | **PASS** | Host /health online，resourceId=n01a-host，protocolVersion=1，能力集合恰为四项 fs；[smoke 回执](../../artifacts/windows/native-n01a/20261028/run-03/smoke.json) |
| N01A-04 | **PASS** | 实际 app.main 构造并进入 lifespan 的 Runtime，其 LocalRuntimeClient/HttpLocalRuntimeTransport 对独立 Host list/read/write/patch；最终磁盘字节 alpha LF gamma LF，共12字节。SHA-256 `17cbbec0b19b84e7729ef8bba7e45944bfa331f56fa873b4e796d1730b8f953f`，另用 PowerShell Get-FileHash 独立复核一致；[回执](../../artifacts/windows/native-n01a/20261028/run-03/smoke.json)、[磁盘内容副本](../../artifacts/windows/native-n01a/20261028/disk-hello.txt) |
| N01A-05 | **PASS** | 错签名 HTTP401 AUTHENTICATION_FAILED；同 nonce 第二次 HTTP409 REPLAY_REJECTED。nonce 首次请求故意用无效 grant，首次和重放均无文件写入；检查负例文件不存在、原文件字节不变；[HTTP 日志](../../artifacts/windows/native-n01a/20261028/run-03/smoke.log) |
| N01A-06 | **BLOCKED** | `../outside` 与真实 Windows junction 写越界均 PATH_OUTSIDE_WORKSPACE，外部哨兵保持原值；但创建目录 symlink 失败 WinError1314，尚不能实测 symlink 请求拒绝。当前令牌没有 SeCreateSymbolicLinkPrivilege，AllowDevelopmentWithoutDevLicense 值不存在。未提权、未启用开发者模式、未放宽 ACL；[回执](../../artifacts/windows/native-n01a/20261028/run-03/smoke.json)、[令牌权限](../../artifacts/windows/native-n01a/20261028/windows-privileges.txt)、[注册表只读结果](../../artifacts/windows/native-n01a/20261028/developer-mode.json) |
| N01A-07 | **PASS** | 真实 HTTP/已装配 client 负例：GRANT_NOT_FOUND、WORKSPACE_MISMATCH、RESOURCE_MISMATCH；缺授权、传入 allowedRoot 均 PROTOCOL_MISMATCH，无副作用；[回执](../../artifacts/windows/native-n01a/20261028/run-03/smoke.json) |
| N01A-08 | **PASS** | 第二个完整 Uvicorn 进程争用在线 AI 同一 workflow DB，退出1，日志明确 another AgentOS runtime owns runtime.instance.lock，首进程仍健康；[第二进程日志](../../artifacts/windows/native-n01a/20261028/run-03/contender.log)、[回执](../../artifacts/windows/native-n01a/20261028/run-03/smoke.json) |
| N01A-09 | **PASS** | 独立 failure-exercise 中 Host 真正健康后、AI 启动前故意失败，Host 回收、端口释放、凭据移除，原服务树仍健康；主 run 随后正常 Ctrl+C 退出，逐个等待子进程，数据库目录可重命名，OS workflow 锁可重取，端口释放；重复 down 也成功，停止后 status 非零。见 [失败回收](../../artifacts/windows/native-n01a/20261028/run-03/startup-rollback.json)、[停止回执](../../artifacts/windows/native-n01a/20261028/run-03/down.json)、[停止后状态](../../artifacts/windows/native-n01a/20261028/status-after-down.json) |
| N01A-10 | **PASS（隔离边界）** | 原容器 ID/镜像清单、全部卷名、PostgreSQL schema-only dump、Docker AI 14个SQLite schema 摘要前后一致；挂载原 JSON 顺序变化，但按 Destination 排序后完全一致。Native 配置无 Docker DB 连接/挂载，不执行 Docker schema upgrade 或卷操作；[比较](../../artifacts/windows/native-n01a/20261028/isolation-and-preservation.json)、[挂载语义比较](../../artifacts/windows/native-n01a/20261028/mounts-semantic-comparison.json)。运行中的原服务可有正常后台数据写入，本轮没有对卷做逐字节冻结，因此不声称卷所有字节静止不变 |
| N01A-11 | **PASS，明确保留1个skip** | 同一 Windows 隔离 venv 中 apps/local-runtime/tests：50 passed / 1 skipped / 153.23s；Chat HTTP E2E：1 passed / 1 warning / 10.86s。symlink 用例的环境 skip 不算 symlink 通过，阻断计入06；[Local 回归](../../artifacts/windows/native-n01a/20261028/pytest-local.log)、[Chat HTTP E2E](../../artifacts/windows/native-n01a/20261028/pytest-agent-http.log) |
| N01A-12 | **PASS（本轮秘密）** | 停止前扫描29个日志/JSON/新增代码与索引，没有本轮随机 HMAC/Fernet key/token 明文；staged diff为空。秘密未放入命令行，调用者环境未写入秘密；DPAPI文件在停止/回收时移除，证据副本不包含凭据文件、SQLite库或venv；[审计](../../artifacts/windows/native-n01a/20261028/run-03/secret-audit.json) |

没有使用 Mock 结果替代上述 Windows 原生文件验收。既有 targeted tests 中的测试 fixture 与正式装配 smoke 是两类独立证据。未配置模型，现有服务日志中会出现“模拟响应模式”的模型初始化提示；本轮没有调用模型生成文件操作，文件、HTTP、HMAC、授权、磁盘复核均为真实实现。

smoke 使用另一个 **真实 app.main 装配进程**和独立 smoke SQLite，在在线 FastAPI/Host 存活期间执行底层 client 调用；并未声称从 Java、浏览器、Chat 模型流或 ACG 任务触发了写文件，也没有新增可任意执行工具的 HTTP 测试端点。

## 6. 复现与当前停止状态

当前两 Native 服务均已停止；保留 run-01/02/03 的测试目录与证据，旧 Docker 服务未停。生命周期入口拒绝复用既有目录；重新复现必须指定不存在的新绝对目录。

```powershell
$py = "$env:TEMP\kinlin-n01a-20261028\venv\Scripts\python.exe"
$entry = '.\ops\scripts\infra\windows\native\native.ps1'
$run = "$env:TEMP\kinlin-native-$([guid]::NewGuid().ToString('N'))"
& $entry preflight -RunDir $run -Python $py
& $entry up -RunDir $run -Python $py -AiPort 18761 -HostPort 18765
& $entry status -RunDir $run -Python $py
& $entry smoke -RunDir $run -Python $py
& $py ops/scripts/infra/windows/native/verify_lifecycle.py $run
& $py ops/scripts/infra/windows/native/audit_secrets.py $run
& $entry down -RunDir $run -Python $py
```

preflight 实测不创建目标目录；PowerShell wrapper preflight 与重复 down 均退出0。当前相同令牌下 symlink 仍应 BLOCKED。首次 smoke 执行时 JSON 已明确记录 BLOCKED，但入口原先仍退出0；已修正最终入口遇 BLOCKED 回执时返回2。该退出码修正经过源码编译检查，发现权限阻断后未再次启动 Runtime 复跑，不能写成已实测 exit2。

针对回归的实际命令：

```text
cwd=apps/local-runtime
<venv>\Scripts\python.exe -m pytest tests -q --basetemp <base>\pytest-local

cwd=<run>，使用隔离环境（不继承 proxy/业务秘密）
<venv>\Scripts\python.exe -m pytest <repo>\apps\agent\tests\test_chat_local_runtime_http_e2e.py -q -rs
```

Agent 测试自带 conftest 将其 SQLite/Chroma 放入仓库忽略的 `.tmp-tests/kinlin-agent-*-tests-<uuid>` 专用新目录，没有复用历史数据。生产 Native run 的所有 SQLite 则位于上述 TEMP run 根内。

## 7. 风险差异、检查与下一阶段依赖

相对于任务文档描述的 N-00 风险，已用新证据关闭：Windows3.14主锁 wheel 可用性；Linux工具锁不可直接用于Windows（以独立平台锁解决）；/app、/run/secrets、cwd 相对路径污染（以隔离绝对路径和受控 cwd 解决）；真实 HMAC 文件链路、nonce、授权、junction containment；单实例和正常/失败回收。N-00 原始完整审计文档未在本轮材料中找到，以上按实施任务内的风险描述对照，不伪造原审计条目编号。

仍开放：symlink 实测权限条件（N01A-06）；最终 BLOCKED 退出码修正的再次运行验证；生产模型、Provider PostgreSQL/Redis 会话持久化、多实例协调、Java→Native网络、Chat审批到模型工具调用、完整 ACG 业务任务与生产灾备均不属于本轮已证明范围。测试工具兼容矩阵也不能推出任意宿主命令或 AppContainer 工具全部可用。

`git diff --check` 退出0，见 [检查回执](../../artifacts/windows/native-n01a/20261028/diff-check.txt)。已有文件有 Git LF/CRLF 提示，未自动格式化它们。新增 Python 文件逐个 `compile` 检查通过；所有新增文件另做空白检查。没有修改任何原 tracked 文件。本报告与新增源码均未暂存/提交。测试证据在仓库已忽略的 `artifacts/windows/native-n01a/20261028/`，并保留 TEMP 原件；它们是本机证据，不会随源码 commit 自动入库。

N01B 的具体必要条件（仅列出，未实施）：

1. 先补齐当前权限条件下无法执行的 symlink 实测，并让最终 smoke 入口复跑确认退出码；由用户/环境管理者提供已具备符号链接能力的合规环境。本轮不修改权限。
2. 评审并实测 Docker Java 到 Windows Native 的受控可达地址、端口及边界。当前 loopback 配置不能直接当成跨容器可达证明，不能用默认0.0.0.0解决。
3. Java/Python 的内部 token、可信用户/租户头、会话重检、SSE断连/取消/超时必须形成端到端验收；不能让容器可达性替代身份认证。
4. 明确选择测试专用 Native 库还是经授权的数据迁移；生产数据若需迁移，先备份、只读 schema 检查、显式 upgrade 和停机/锁策略。不能把当前新空库当作生产历史已迁移。
5. 决定 Docker AI 与 Native Python 的职责和流量切换/回滚条件，避免双写同一 SQLite；保护现有 PostgreSQL/Redis 与 Docker卷，单实例限制继续生效。
6. 单独验证 Provider State、协调 Redis、模型可用性和 ACG Permit/Review 的正式任务链路，再决定是否允许下一阶段冻结。

最终判断：**独立的 Windows 原生最小文件运行链路已真实可用；PR-N01A 整体验收因 symlink 子项 BLOCKED，尚未 ACCEPT。**

## 8. PR-N01A-R1 补充验收（2026-10-28，Asia/Shanghai）

### 8.1 本轮结论与保护范围

**本轮结论：BLOCKED；不能标记 ACCEPT。** 已真实验证最终 `native.ps1 smoke` 的 BLOCKED / exit 2 和 FAIL / exit 1；尚缺合法的真实 symlink 夹具，不能执行 symlink HTTP 越界负例，也不能实测完整 smoke 全 PASS / exit 0。纯汇总逻辑的 PASS / 0 检查不算安全端到端通过。

当前 HEAD 仍是 `8b792fa0c2c422ed7548330ae3f1ea5bbf50883d`。本轮只修改已有 N01A 工具的 `native.ps1`、`native_runtime.py`、`smoke.py`、`README.md` 及本报告；没有新增平行测试框架，没有修改业务 Runtime 或 ACG 执行语义，也没有重新安装/调整依赖锁。

此前 21 个 tracked 修改和原有 Chat untracked 源码/记录逐文件 SHA-256 未变，tracked binary diff 和 staged diff 均与本轮进入时一致，索引仍为空。原始 `artifacts/windows/native-n01a/20261028/` 的 **75 个证据文件**完整保留，前后文件清单和 hash 全部一致。见 [保护核验](../../artifacts/windows/native-n01a/20261028-R1/preservation.json)。报告修改前原件另存 [report-before-R1.md](../../artifacts/windows/native-n01a/20261028-R1/report-before-R1.md)。本轮未调用 Docker 或数据库管理命令，未修改 Docker、Spring Boot、PostgreSQL、Redis，不进入 N01B，不自动暂存/提交 Git。

### 8.2 symlink 夹具准备与 Runtime 执行已分离

新增已有入口动作 `native.ps1 fixtures`，在独立目录、两个服务启动之前运行，既不导入 `app.main`，也不启动 Local Runtime：

1. 先只读检查现有 `workspace/symlink`。必须是 Windows **IO_REPARSE_TAG_SYMLINK = 0xA000000C**；junction 不满足条件。
2. 链接必须位于本轮 workspace，目标限定为本轮 workspace 外的临时 `outside` 目录或 `outside/sentinel.txt`。不会复制/移动其他工作区的链接，不接受历史服务数据目录。已有哨兵保持原内容。
3. 只有没有可复用链接时，准备动作才尝试普通用户 `symlink_to`。WinError 1314 明确产生 BLOCKED，不提权、不启用开发者模式、不放宽 ACL。
4. `up` 只接受不存在的新目录，或带有可核验准备回执的 fixture-only 新目录；检查无历史 Runtime 数据、哨兵 hash 未变。新目录直接 up 时也在任何 Runtime 启动前执行准备阶段。
5. `smoke` 执行阶段不再创建/修复 symlink 或 junction，也不重置哨兵；只消费夹具，并核对准备时间早于 Runtime 启动时间。

在有合法夹具的环境中，现有脚本会通过正式装配的 LocalRuntimeClient / HMAC HTTP 执行 symlink 的 read、overwrite-write、patch；目录链接再执行 list 和 new-file-write。每个适用负例必须返回 `PATH_OUTSIDE_WORKSPACE`，同时核对外部哨兵内容/hash/mtime 和目录条目不变。**这些 symlink 分支本轮没有执行，不计为 PASS。** `../` 与真实 junction 的独立负例仍保留并实际通过。

正向文件操作改为 workspace 内 `files/hello.txt`，list 也使用 `files/`。原因是夹具提前准备后，workspace 根目录包含越界 reparse point；既有 Host 按策略拒绝 list 根目录。本轮没有放宽该策略，正常目录的 fs.list/read/write/patch 仍走相同生产链路。

### 8.3 当前 Windows 条件与实际夹具结果

本轮目录：`C:\Users\LZX\AppData\Local\Temp\kinlin-n01a-r1-20261028-202516\run`。继续使用原来已锁定并校验的 Windows 3.14.5 隔离 venv，没有改用全局 Python 包。

只读检查旧 `run-03/workspace`，只有 `junction` 与 `hello.txt`，没有真实 symlink。用户也确认没有提供已准备的 symlink，要求合法条件不足时保留 BLOCKED。当前用户令牌缺少 `SeCreateSymbolicLinkPrivilege`；`AllowDevelopmentWithoutDevLicense` 注册表值仍不存在。前后只读结果一致，未更改系统设置。见 [已有夹具](../../artifacts/windows/native-n01a/20261028-R1/existing-fixtures.json)、[令牌权限](../../artifacts/windows/native-n01a/20261028-R1/windows-privileges.txt)、[开发者模式读取](../../artifacts/windows/native-n01a/20261028-R1/developer-mode-before.json)。

真实 `native.ps1 fixtures` 结果为 **BLOCKED / exit 2 / WinError 1314**；准备回执明确早于服务启动，见 [夹具回执](../../artifacts/windows/native-n01a/20261028-R1/run/fixture-preparation.json)、[退出码](../../artifacts/windows/native-n01a/20261028-R1/fixtures-exit.json)。

随后普通权限启动原有两个生产服务：Host launcher PID **43584** → Python **31544**，AI launcher **21500** → Python **30232**。直接查询各个实际 Python 进程的 Windows token 均为：

```text
elevated = false
integritySid = S-1-16-8192  (Medium)
symlinkPrivilegePresent = false
symlinkPrivilegeEnabled = false
```

见 [实际进程树及 token](../../artifacts/windows/native-n01a/20261028-R1/run/up.json)。查询使用 TOKEN_QUERY，没有调整 token；preflight 还会拒绝 elevated / high integrity 的验收启动条件。监听仍是 `127.0.0.1:18761` 与 `127.0.0.1:18765`，workers=1，Shell 未启用，Semantic/C2/Dispatch 门禁保持不变。

### 8.4 smoke 结果与退出码真实复验

汇总规则现在明确为：**FAIL 优先于 BLOCKED；全部 smoke 检查 PASS 才返回 0**。worker 非零退出、缺少/无效/过期回执、检查项缺失或状态未知均为 FAIL。每次使用独立 invocation ID、日志、回执和 smoke 数据库，核验本次 worker 回执身份，避免上次结果被误用。`smoke.json` 是当前调用的汇总，不会抹掉按 invocation ID 保存的原始回执。

| 场景 | 真实执行和结果 | 判定 |
|---|---|---|
| Runtime 均在线，缺少合法 symlink 夹具 | 直接运行最终 `native.ps1 smoke`；invocation `663fdb70`；worker 完成并退出0，控制器看到 N01A-06 BLOCKED 后返回 **2**，汇总 status=BLOCKED，其余7个 smoke 检查 PASS | **PASS：BLOCKED 退出码验收**，不代表 symlink 通过 |
| 真实 Host 不可用，且已有上一轮 BLOCKED 回执 | 核验身份后只停止本轮 Host，AI 仍 ready；再次直接运行相同 `native.ps1 smoke`；新 invocation `c01cac8c`；新 worker 观察 Host absent，退出1；新汇总 status=FAIL，PowerShell 返回 **1**。未复用 `663fdb70` 回执 | **PASS：FAIL 退出码及新回执隔离验收**；这是受控失败场景，不是安全实现被判 REJECT |
| 所有 smoke 检查真实 PASS | 当前无法准备 symlink 夹具，不能构造完整真实通过运行；没有跳过06、伪造夹具或将 junction 当作 symlink | **BLOCKED：真实全 PASS / exit 0 尚未实测** |
| 汇总函数纯逻辑契约 | 7个契约检查验证 PASS→0、BLOCKED→2、FAIL→1、FAIL优先、worker失败、缺项/未知状态等 | **PASS（仅逻辑契约）**，不能替代上一行的真实安全验收 |

真实命令及证据：

```powershell
$py = "$env:TEMP\kinlin-n01a-20261028\venv\Scripts\python.exe"
$entry = '.\ops\scripts\infra\windows\native\native.ps1'
$run = "$env:TEMP\kinlin-n01a-r1-20261028-202516\run"
& $entry fixtures -RunDir $run -Python $py  # 本轮：2，准备阶段 BLOCKED
& $entry up -RunDir $run -Python $py        # 本轮：0，真实普通用户进程
& $entry smoke -RunDir $run -Python $py     # 本轮：2，663fdb70
# 单独核验并停止 state.json 中本轮 Host；未按进程名终止服务，AI 保持健康
& $entry smoke -RunDir $run -Python $py     # 本轮：1，c01cac8c，真实 Host absent
& $py ops/scripts/infra/windows/native/audit_secrets.py $run
& $entry down -RunDir $run -Python $py      # 本轮：0
& $entry status -RunDir $run -Python $py    # 本轮：1，两个服务均已停止
```

[BLOCKED 退出码](../../artifacts/windows/native-n01a/20261028-R1/smoke-blocked-exit.json)、[BLOCKED 完整回执](../../artifacts/windows/native-n01a/20261028-R1/smoke-blocked-receipt.json)、[原始 HTTP/worker 日志](../../artifacts/windows/native-n01a/20261028-R1/run/smoke-663fdb70.log)、[真实失败准备](../../artifacts/windows/native-n01a/20261028-R1/real-failure-setup.json)、[FAIL 退出码](../../artifacts/windows/native-n01a/20261028-R1/smoke-fail-exit.json)、[FAIL 回执](../../artifacts/windows/native-n01a/20261028-R1/smoke-fail-receipt.json)、[汇总逻辑契约记录](../../artifacts/windows/native-n01a/20261028-R1/exit-code-contract.json)。没有用 Mock 替代 Runtime、HMAC、Windows token 或文件系统检查。

### 8.5 无副作用与退出清理

真实 `../` 和 junction 负例均返回 `PATH_OUTSIDE_WORKSPACE`。外部哨兵一直保持：

```text
内容：untouched
SHA-256：d59c2a5f721ce135ce54628b1ad8ad8b8eb26c8bbe2e2abe1cdca97e2d6ab446
mtime_ns：1793190515647647600
outside 目录条目：仅 sentinel.txt
```

smoke 回执已检查字节、hash、mtime 和目录条目；[磁盘哨兵副本](../../artifacts/windows/native-n01a/20261028-R1/sentinel-after.txt)和[实际安全回执](../../artifacts/windows/native-n01a/20261028-R1/smoke-blocked-receipt.json)保留。symlink 请求数为0，因为 fixture 准备失败；不能将这一无副作用观察当成已证明 symlink 拒绝。

最终 down 实际通过：两条服务及两个 smoke worker 的4个所属进程记录均不存在；按 run cwd/命令参数检查无残余进程；18761/18765 可独占绑定；lifecycle 锁可重新取得；主 AI、BLOCKED worker、FAIL worker 的 **3 个 workflow OS 锁**均可重新取得；**37 个 SQLite 文件**以 Windows OPEN_EXISTING、share=0 独占打开检查成功，未修改数据库字节；DPAPI 凭据文件不存在。见 [down 回执](../../artifacts/windows/native-n01a/20261028-R1/run/down.json)、[独立清理复核](../../artifacts/windows/native-n01a/20261028-R1/cleanup-verification.json)、[停止后 status 退出码](../../artifacts/windows/native-n01a/20261028-R1/status-after-down-exit.json)。测试数据和全部原始日志保留，没有递归清理目录。

停止前本轮秘密审计扫描29个日志/JSON/新增工具文件，未发现随机 HMAC/Fernet/token 明文，索引仍为空；[秘密审计](../../artifacts/windows/native-n01a/20261028-R1/run/secret-audit.json)。证据副本不含 SQLite 数据库、DPAPI 凭据或 venv。

### 8.6 12 项最新状态与剩余必要条件

| 项目 | 本轮后判定 | 证据时效与范围 |
|---|---|---|
| N01A-01 / 02 / 03 / 04 / 05 / 07 / 08 | PASS | R1 真实 smoke 再次执行，详见 `663fdb70` 回执；文件四项操作、HMAC/授权负例及争锁均保持通过 |
| N01A-06 | **BLOCKED** | R1 重新执行 `../`、junction 并通过；symlink 独立夹具准备仍 WinError1314，未执行 symlink HTTP 负例 |
| N01A-09 | PASS | 原失败启动回收证据保留；R1 对两种 smoke 结果后的进程、端口、lifecycle/3个workflow锁、37个SQLite文件、凭据做了真实清理复核 |
| N01A-10 | PASS（沿用原隔离证据） | R1 未操作 Docker 或业务数据库；原75个证据文件未变，不将本轮源码保护检查冒充新一次 Docker 数据取证 |
| N01A-11 | PASS（沿用原回归，仍保留1个skip） | 本轮没有重新运行此前50 passed / 1 skipped与Chat HTTP 1 passed的整套targeted tests；仅运行本轮相关真实smoke及汇总契约，不把旧回归写成新回归 |
| N01A-12 | PASS（本轮秘密） | R1 已重新审计及确认临时凭据删除，未暂存或提交 |

源码编译、Markdown证据链接、空白检查与保护核验见 [R1 源码检查](../../artifacts/windows/native-n01a/20261028-R1/source-verification.json)；Git diff check 见 [检查退出码](../../artifacts/windows/native-n01a/20261028-R1/diff-check.json)。

要解除剩余 BLOCKED，必须具备以下合法环境条件之一，而不是给 Local Runtime 增加权限：

- 由环境所有者在**新的专用临时目录**预先准备真实 Windows symlink：`<new-run>\workspace\symlink` → `<new-run>\outside` 或 `<new-run>\outside\sentinel.txt`；其中 `outside` 是真实临时目录，`sentinel.txt` 是真实临时文件，普通 Runtime 用户本来就能读取测试所需元数据。执行 `fixtures` 只读识别并复用它，然后以普通用户启动 Runtime；或使用本来就具备合法普通用户 symlink 创建能力的环境。本轮没有创建提权进程、调整系统策略或 ACL。
- 在该条件下重新运行正式 HMAC HTTP 的 symlink read/write/patch 等适用负例，得到拒绝和无副作用的实证；再真实运行 `native.ps1 smoke`，确认完整 smoke 的 status=PASS / exit0，并完成停止清理。当前纯汇总契约的0退出值不能补足这一步。

**R1 最终判定仍为 BLOCKED。Windows 原生最小运行链路可用这一结论保持；N01A-06 和真实全 PASS / exit0 仍未闭合，所以 N01A 不能 ACCEPT。N01B 未实施。**
