# PR-EX-M2B：动态工作区 ACG / Hands 端到端验收

日期：2026-10-29—2026-10-30。状态：**SELF-TESTED，存在明确 FAIL 和 BLOCKED；不作独立 ACCEPT 结论**。

本记录基于 Windows 真实进程、Electron 界面、真实 DeepSeek 模型、正式 Run、HMAC HTTP 和磁盘文件。组件回归与真实端到端证据分开列出。入场及最终 HEAD 为 master `f7700affdc9f3b7173521bc94819c6b09e31c210`；没有 commit、push、merge 或部署。

原始证据目录：[artifacts/windows/pr-ex-m2b-20261029](../../artifacts/windows/pr-ex-m2b-20261029)。其中初次失败、诊断、后续修复和复验日志均保留，不以最后一次通过覆盖早期失败。

## 1. 入场与保护边界

已读取 M1、文件编辑器、M2、EX-00、HANDS-02 报告、最近三个提交完整 diff，以及本轮任务指定的真实实现。没有重做 M1，也没有引入第二个 Runtime、Workspace 数据库、Scheduler 或执行账本。

入场已有前端 package/lock、ChatView、WorkspaceFileEditor 和 syntaxHighlight 修改；详见 `git-status-before.txt`、`preexisting-files.json`。没有恢复、覆盖或暂存这些文件。实施期间另有用户并发修改编辑器、状态栏、ProblemsPanel、EditorGroup 和 MissionWorkspaceView；这些不计入本轮源码修复。最终回归另行覆盖当前前端，不沿用旧前端快照结论。

保护 default、ex-m1-20261029、ex-m2-20261029 的环境配置、DPAPI、Grant 及 runtime-state，11 个文件摘要核对见 `protected-before.json`、`preservation-current.json`。没有对这些环境执行启停、恢复、迁移或业务写入。原有容器资产的状态沿用入场代码，本轮未操作 Docker、旧数据卷或系统服务。

当前 Windows 令牌未提权，缺少 SeCreateSymbolicLinkPrivilege，开发者模式未配置，见 `windows-token-readonly.json`。未提权、未修改开发者模式、未放宽 ACL。原生 Python 环境实际缺少 requirements.txt 已声明的 psycopg，补装缺失的 3.3.6 依赖并修复锁文件；未重建或删除共享 Python 环境，也未升级其他已有依赖。

## 2. 隔离环境及实际调用链

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

## 3. 最小源码修复

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

## 4. 动态授权与安全边界

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

## 5. 真实 Mission：失败、修复、复测与交付

测试输入是可丢弃 Node 项目，基线 reverseText 错误返回原字符串，已有断言要求 abc→cba。基线文件摘要见 `project-before.json`。后续源码和测试结果由 ACG/Hands 实际生成，未人工预写完成文件。

### 5.1 首次审批超时的失败保留

Mission `mission_328918d01fdc`，Run `run_e2e9e0bac505`，Permit `xpermit_2bf441241cb36f58057dd113c9b38eea5320e3d6`。只有四份 read/list 收据；首次 node 测试审批在用户响应前按既有 300 秒期限到期，Run FAILED，无写入或命令 admission。没有调整超时、自动补批或重放。

真实 UI 恢复分别被“Permit retry must retain its formally activated Run”和“unsettled external operation requires explicit side-effect reconciliation”拒绝。保留 409，不编辑旧 Run；这是当前保守恢复能力的实际限制。确认没有写/命令 admission 后另建正式 Mission，重新申请 Permit。

### 5.2 正式开发 Run

Mission `mission_d5fcefb6390f`，Run `run_e59fe12d8bf6`。通过真实 Electron 创建、规划、准备图、激活暂停、交接、Permit、执行，用户在真实界面批准四项写/命令操作。

- Hands 读取现有项目，真实 `node.EXE --test` 首次退出 1（abc 不等于 cba），收据 `xhexec_61382afd5f23e854d09553d2`。
- Hands 写入 `src/text.js` 和 `test/text.test.js`，实现字符串反转、回文判断、单词统计与测试。
- 真实复测退出 0，13/13，通过收据 `xhexec_9107e6dd7f5e4eff2130c92c`；失败输出确实反馈给执行节点，没有把 202 当成功。
- 14 份收据均以生产 HMAC 查询并验证 checksum、Run/Step/Attempt/Commit。错误目录 tests 的 FS_NOT_FOUND 与首次测试失败均保留。
- Run completed，但本次额外任务要求的 patch_file、npm-test 没执行，canonical **准确标为 PARTIAL**，也指出上游不准确的 Python 开发摘要；因此不将该 Run 描述成全部要求通过。
- canonical V2 identity `artifact_9d3ca06c36c3`，producerAttempt `attempt_57bc9633b10d`，manifest `manifest_6151749338c8482db7a022616916a6a1`，18897 字节，SHA-256 `290c0585b182807a7dfe62c7404dc222b3c29c24bbd4a0384c340d4bcee1daa7`。

证据：`completed-main-capture.json` 及同前缀 run/output/hands/trace/provenance/final 文件。Markdown 是通过正式输出引用从应用取回，并非人工生成交付物。

### 5.3 补充正式 patch / npm Mission

用户后续明确授权由执行代理逐项审查并点击真实界面的“允许本次操作”。仍通过原审批 UI，不调用后门自动批准或改变 ASK 策略。

第一次补充规划 `run_7c763d7cbb8d` 被 CONTROL_BARRIER_BLOCKED 拒绝，未执行；保留 trace，不放宽控制策略。改为明确顺序任务，真实 Electron 创建 Mission `mission_61793feb3a01`、Run `run_7c0dee91a6fd`，Planner 接受四节点任务图。

Permit `xpermit_3e274c9a97a1d51a271f5636a9afc0c61049e6c6`，Planning Commit `pcommit_f17527975c3d4123ac585f352d5d6957`，graph `initial_9df51483f20e5d9e3e043b9ede164ead482e00b6` v1。通过正式 UI 检查并批准 `npm.cmd test` 基线、源码 patch、测试 import patch、测试新增 patch 和最终 npm 复测。

Hands 在同一冻结工作区追加 normalizeWhitespace，检查非字符串 TypeError、Unicode 空白与 trim，增加四项测试。最终收据、canonical 和冷重启比较见本报告末尾补充结果及原始 capture。

### 5.4 额外真实协议与故障回归

- `python-runner-signed-regression.json`：独立测试目录由真实 Workspace API 授权，生产 HMAC/Hands transport 执行五次操作，pytest 1 failed → fs.patch → pytest 1 passed；记录命令、退出码、输出与 checksum。**这是协议回归，不是另一个正式 ACG Mission**。
- 复用 `hands_checks.py`，真实独立进程在 STARTED 后异常退出，恢复 UNKNOWN；同幂等键及变化客户端 requestId 均不重放，未知文件不存在。真实取消产生 CANCELLED 封章收据，无延迟副作用；所属进程、19366 端口和临时 key 清理通过。详见 `exception-checks.json`。

## 6. 回归与原始失败

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

## 7. 冷重启、快照与最终状态

第一次正常 down/up 已确认四份只读收据、旧 Run、绑定与文件保留；同时发现 receipt updatedAt 恢复不一致并作上述最小修复。最终写入任务完成后的正常冷重启、当前前端快照、授权撤销状态与清理结果在下方追加；不得用首次只读 Run 的冷启动替代有副作用 Run 的验收。

当前已知限制：真实 symlink 夹具 BLOCKED；Hands 扩大门禁一项 FAIL；审批到期后的正式恢复仍需显式对账支持；host-approved Shell 不是 OS 沙箱；Memurai Developer 仍受 N03 已记录的开发许可证限制。本轮不涉及安装包、系统服务、自动更新、商业发布或独立验收。

### 最终补充结果（2026-10-30）

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

### 最终清理及命令记录

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
