# 架构与工程卫生审查报告（2026-11-21）

> 范围：`E:/Project/Kinlin_AI` 全仓只读审查。证据均为源码/配置实测，未修改任何源码文件。
>
> **版本**：v2（含第二轮深入复查）。第一轮聚焦应用边界/依赖/布局；第二轮补查后端与桌面端内部、内核遗留与测试健康度、文档声明与实现一致性。v2 修正了 v1 的两处事实错误（CI 数量、许可证类型），见第六节。

## 〇、整改状态快照（v2 新增，2026-11-21 19:17 复核）

v1 报告提交后，master 已从 `7074e474` 前进到 `a7708787`，5 个新提交恰好覆盖 v1 的多数建议。**复核确认 v1 问题大部分已修复**：

| v1 问题 | 当前状态 | 证据 |
| --- | --- | --- |
| P0-1 README 测试路径失效 | ✅ 已修复 | `README.md:213,215` 现为 `TEST/tests`、`apps/agent/tests` 正确命令 |
| P0-2 backend-ts 改名未收尾 | ✅ 已修复 | `README.md:170` 现 `Push-Location apps/backend`；包名 `@zhiyi/backend`；`check_repository_hygiene.py:14` 的 `STALE_PATHS` 已纳入 CI 防回归。`ZHIYI_BACKEND_TS_*` 是 README:186 声明的有意保留兼容接口，非遗漏 |
| P0-3 前端双栈并存 | 🟡 部分 | `ba2799ba` 清理了死代码；但旧 `ChatView.vue` 4823 行、新 `MissionWorkspaceView.vue` 1508 行两套栈仍并存（见第五节 F-3） |
| P0-4 依赖多真相源 | ✅ 已修复 | requirements 从 7 个收敛为 4 个：`requirements{.in,.lock}` + `requirements.dev{.in,.lock}`；根新增 `.python-version`(3.14)、`.node-version`(24.22.1)；CI 用 `python-version-file` 引用 |
| P1-1 前端死代码 | ✅ 已修复 | `ba2799ba` 提交 |
| P1-2 worktree + 三入口 | ✅ 已修复 | 仅剩 1 个 codex 协作 worktree（`a7708787`，无落后）；`start-native.bat` 已删除 |
| P1-3 papers 526MB 入库 | ✅ 已修复 | `b1d63051` untrack，跟踪数从 629 降到 118（保留研究索引） |
| P1-4 多套测试目录 | 🟡 保留 | 结构仍在，但职责已厘清、文档已同步，属合理分层 |
| P2-1 无 monorepo / TS 版本漂移 | ✅ 已修复 | `check_package()` 统一 TypeScript 5.9.3、Node >=24.9.0 <25，6 个包全部校验 |
| P2-2 CI 覆盖 | ✅ v1 判断错误，实际已覆盖 | 现有 2 个 workflow，`application-ci.yml` 覆盖 Python 内核/应用/启动器、frontend、4 个 TS 包；见第六节修正 |
| P2-3 配置分散 | ✅ 基本修复 | `runtime-defaults.json` 成为单一端口/SSE 合同（README:186），Python/TS/启动器共读 |
| P2-4 docs 双树堆积 | 🟡 部分 | `a7708787` 记录了验证，但 docs 历史文档体量仍在，建议归档收口（见第五节 F-8） |

**净结论**：v1 的 P0/P1 硬伤已基本清零。第二轮在更深的盲区找到 **1 个新的 P0（实时 ASR WebSocket 端点缺失）+ 若干 P1/P2**，以及 **3 处 README 与实现不符**（测试数字、节点/边类型数、许可证）。详见第五、六节。

## 一、结论摘要

核心架构设计**没有结构性缺陷**，不需要重构：

- `apps/agent` 是 FastAPI 应用层（组合根 + API 投影 + 适配器 + services），`apps/agentOS` 是 ACG 内核，二者单向依赖 `agent → agentOS`，无反向依赖。
- 全仓仅 1 个活跃执行真源：`apps/agentOS/src/runtime/workflow_runtime.py:9 class ExecutionRuntime`，类体在 `apps/agentOS/src/runtime/orchestration/workflow.py:228 RuntimeApplication`。
- 名字相似的组件（compiler、checkpoint、broker、store）经核对均为职责不同的查询投影/读模型/转发层，不是第二套实现。C4 旧内核已在历史提交中删除。

**真正的问题是"迁移欠债 + 工程卫生"**：多次重命名和架构收敛只改了代码主体，文档、脚本、配置、前端 UI 和磁盘残留没有同步收尾。这让仓库显得冗杂，也带来实际运行风险（按 README 操作会失败、CI 漏测、端口冲突）。

## 二、不要动的部分（避免误伤）

| 现象 | 判定 | 依据 |
| --- | --- | --- |
| `support/acg/__init__.py` 大量重导出 | 兼容转发层，已收敛为"只转发" | `2026-11-16` 架构收敛审计 L158 |
| `storage/` 与 `support/stores/` 两套 store | schema 隔离，职责不同，勿合并 | `apps/agentOS/README.md:156`、审计 L101 |
| `runtime/events/live_events.py` vs `communicator/broker.py` | 前者是 SSE 进程内事件，后者是业务低熵投递 | README L151 |
| `platform/electron` + `apps/desktop/electron` | 渲染进程侧 / 主进程侧分层，设计合理 | `vite.config.ts:23-26,100`、`preload.ts:12-13` |
| `app/execution/runtime.py` | 纯导入边界（21 行转发），非第二运行时 | 自初始提交起即如此 |
| `features/*` + `components/*` + `services/*` 同主题出现 | 逻辑/UI/API 正常分层，非重复 | 前端调研逐项核对 |

## 三、问题清单

### P0 — 立即修复（影响可用性与正确性）

**P0-1 文档与物理布局断裂**
`README.md:205-207` 写 `Set-Location apps/agentOS; python -m pytest tests -q`，但 `apps/agentOS/` 下**不存在 `tests/` 目录**。测试已在提交 `1c63269b` 迁到仓库根 `TEST/tests/`（301 个文件）。README 的"1730 cases"表同样仍指向旧路径。任何人按快速开始操作都会失败。

**P0-2 `backend-ts → backend` 改名未收尾**
git 提交 `5a4465e6` 以 R100 整体重命名了目录，但以下仍指向已不存在的 `apps/backend-ts`：
- `README.md:170, 213, 229, 238, 260`（含快速开始第 2 步 `Push-Location apps/backend-ts`、项目结构树）
- `ops/scripts/release/assemble_portable.py:148,149,488-490,511`
- `ops/scripts/release/product_runtime.py:213,382`
- `ops/scripts/runtime_streaming_combined_acceptance.py:96,98`
- `ops/scripts/infra/windows/native/README-N03.md:28`、`README-EX-M1.md:20`
- `ops/scripts/infra/tests/test_persistent_startup.py:19,22`、`test_backend_watch.py:15,18,22`
- 代码内残留：`apps/backend/package.json:2` 包名仍为 `@zhiyi/backend-ts`，`apps/backend/src/config.ts:18,22` 错误信息、`test/fixtures.ts:15` 临时目录前缀。
正确写法见 `persistent_runtime.py:319,496`（`cd apps/backend && npm ci`）。

**P0-3 前端新旧两套 UI 栈并存**
- 旧栈：`views/ChatView.vue`（**4824 行**）直接引入 `components/agentos/Acg*` 六件套（`ChatView.vue:610-616`）。
- 新栈：`views/MissionWorkspaceView.vue`（1508 行）有 24 处引用 `@/workbench`、`components/workbench`、`components/workspace`。
- 路由已开始收编旧入口：`router/index.ts:58,83,88,93,98,175-178` 中 `/roles`、`/federated-*`、`/agentos-console` 全是 redirect；`views/AcgEntryView.vue` 只是跳转桥接页。
结论：新 Workbench 栈是未来主线，旧栈是迁移残留。同主题三套 Run Inspector（`AcgRunInspector.vue` 438 行、`RuntimeInspector.vue` 441 行、`ProjectRunInspector.vue` 35 行）就是直接后果。

**P0-4 依赖真相源冲突**
`apps/agent/` 有 7 个依赖文件，实际安装链只用 2 个：`requirements.lock` + `requirements.native-tools.lock`。其中 `requirements.in`、`requirements.txt`、`requirements_minimal.txt`、`requirements_tools.txt`、`requirements.tools.lock` 无启动脚本引用。版本冲突实例：
- pydantic：`requirements.in ==2.13.4`、`requirements.txt >=2.7.4,<3.0`、`apps/agentOS/requirements.txt:12 ==2.12.5`（三种）
- fastapi：`==0.139.2` vs `>=0.116,<1`
- `apps/agentOS/requirements.txt:1-8` 自称"唯一 Python 环境入口"，但 N03 启动链仍装 apps/agent 的 lock——两套"唯一入口"并存。

### P1 — 尽快清理（冗余与风险）

**P1-1 前端死代码**
- `components/federated/` 整个目录失活（5 个 .vue，外部 0 引用；路由已全部 redirect，最后改动 2026-10-06）。
- `components/agentos/` 中 8 个组件外部 0 引用，其中 `AcgProvenancePanel.vue`、`CallResultPanel.vue`、`HumanReviewPanel.vue`、`RunResourceStrip.vue` 连 spec 都没有。
- 知识图谱双实现：`KnowledgeGraphView.vue`（264 行，全项目 0 引用）vs `KnowledgeGraphVisualization.vue`（566 行，被 `RagView.vue:134-135` 使用）。
- 生产代码 0 引用且无 spec：`utils/search.ts`、`utils/errorHandler.ts`、`utils/performance.ts`、`utils/acgAuditExport.ts`、`composables/useThrottle.ts`、`composables/useScrollToBottom.ts`、`services/api/roleFusion.ts`。

**P1-2 三入口指向同一 runtime + 陈旧 worktree**
- `start-native.bat`、`ops/scripts/infra/windows/native/persistent.ps1`、`ops/scripts/start-local-desktop.ps1` 都调用 `persistent_runtime.py`；README 只承认 `persistent.ps1`，根目录 `.bat` 全仓无文档引用。
- 4 个已注册 worktree 全部**领先 master 0 提交**（无未合并工作）：`companion-experience` 落后 27、`integrate-all-20261116` 落后 0（精确停在 master HEAD 的冗余检出）、`local-tools-baseline` 落后 128、`safe-unified-env` 落后 23。
- `.worktrees/` 另有 6 个未注册孤儿目录：`acg-step-route`（30684 文件）、`acg-swimlane-graph`（31672）、`edge-cloud-runtime`（1396）、`local-tool-marketplace`（44293）、`resource-operations-multitype`（1406）、`resource-plane-test-hardening`（2413）。

**P1-3 papers/ 526MB 全量入库**
`papers/` 650 文件 / 526MB / git 跟踪 629 个（201 篇 PDF + 148 txt + 大量 drawio/png）。`.gitignore` 忽略 `*.zip`、`*.onnx`、`*.pt` 等大二进制，却漏掉 PDF——策略不一致。`papers/architecture/*/.build/` 下还有被跟踪的构建中间产物。

**P1-4 多套测试目录 + 测试残留**
正式测试在 `TEST/tests/`（301）；另有 `apps/agent/tests/`（83）、`evals/`（14，SAFE 评测）、`ops/scripts/infra/tests/`（11）、两处 TS 组件测试。跨目录同名 `test_model_runtime.py` 内容不同（一个测内核适配器，一个测应用层），属命名冲突非冗余。磁盘残留：`.tmp-tests/` 4058 文件、`tmp/` 8853 文件、`data/` 27164 文件 / 4.2GB（已被 gitignore 正确忽略，但需定期清理）。

### P2 — 规范建设

**P2-1 无 monorepo，TS 版本漂移**
无根 `package.json` / `pnpm-workspace.yaml`；6 个 package.json 各自 npm ci。typescript 有 4 个版本（5.9.3 / 5.4.5 / ^5.9.3 / ^5.6.0 / 5.6.3），vitest 跨主版本（5.1.0 / ^2.1.9 / ^3.0.0）。`apps/desktop/` 有 `package-lock.json` 却无 `package.json`（孤儿 lockfile）。

**P2-2 CI 覆盖已较完整（v2 修正：v1 判断有误）**
v1 称"唯一 workflow 只跑 backend"是**错误**的。实际有两个 workflow（`.github/workflows/` 下 `backend-ci.yml` + `application-ci.yml`）：`application-ci.yml` 覆盖 Python 内核（`TEST/tests`）、应用层（`apps/agent/tests`）、原生启动器、frontend 双构建+测试、以及 desktop/terminal/hands/compact 四个 TS 包的 typecheck+test，还有仓库卫生检查 `check_repository_hygiene.py`（其 `STALE_PATHS` 含 `apps/backend-ts`、`apps/agentOS/tests`，防失效路径回归）。CI 现状**不是问题**。
真正的残留：CI 用 `.python-version`/`.node-version` 固定版本（这是优点），但 README 正文仍写死 Node 24 / Python 3.14，两处口径需要同步策略；`application-ci.yml` 缓存路径含 `apps/agent/requirements.dev.lock`——该文件在仓库中并不存在（见 P0-4 依赖清单），会导致 pip 缓存退化为不命中，需核实。

**P2-3 配置分散且冲突**
- 无 `.python-version` / `pyproject.toml`；版本散落 README(3.14)、CI(3.14)、native_runtime.py(接受 3.13)、persistent_runtime.py(3.13/3.14)、`apps/agentOS/requirements.txt`(**3.10**)。
- 端口常量至少 4 处重复：`persistent_runtime.py:30` 的 8 端口、`backend/src/config.ts:20`、审计 capture 脚本、`.env.windows`。`.env.windows` 的 `KINLIN_HTTP_PORT=8080` 与实际 N03 端口 18080/15200 冲突，且代码根本不加载它（`apps/agent/app/config.py:54-71` 只读 `.env`，仓库中无 `.env`）。
- SSE 心跳、最大时长、`PROVIDER_STATE_ENABLED` 默认值在 `.env.windows` 与代码间不一致。

**P2-4 docs 双树堆积**
根 `docs/`（320 文件）与 `apps/agentOS/docs/`（55 文件）各有归档/迁移报告序列。典型堆积：`docs/audits/` 下同一 INT-2E 事件有 8 层评审补丁（FIX → FIX-REVIEW → REMEDIATION → ...-6-PERFORMANCE-REVIEW，编号跳过 4）；`PR-TS-00-20261107/` 单次审计派生 18 份文档；`2026-11-18-evolution-safe-layers` 在 plans/specs/reports 三处各一份。

## 四、调整路线图

### 第 1 步：恢复"文档 = 代码"（半天，零风险）— ✅ 已完成
1. 全文替换 `backend-ts` → `backend`（README、ops 脚本、包名、错误信息、测试前缀）。
2. README 测试命令改为 `python -m pytest TEST/tests -q`，更新 1730 cases 表格路径。
3. 删除根目录 `start-native.bat`（或改造成调用 `persistent.ps1` 的薄封装），统一入口为 README 已声明的 `persistent.ps1`。
4. 加一个 CI 检查：扫描 `backend-ts`、`apps/agentOS/tests` 等失效路径，命中即失败。防止回归。

### 第 2 步：收敛依赖与配置（1–2 天）— ✅ 已完成
1. 确定唯一真相源：以 `apps/agent/requirements.in` → `requirements.lock`（hash 锁）为准，删除 `requirements_minimal.txt`、`requirements_tools.txt`、`requirements_tools.lock`；把 `requirements.txt` 精简为开发/测试 extras 或删除。
2. 给 `apps/agentOS/requirements.txt` 明确定位（仅内核独立开发用）或与主锁合并，消除"两个唯一入口"。
3. 加根 `.python-version`（3.14）与根 `package.json`（workspaces + 统一 devDependencies），用 `pnpm-lock.yaml` 收敛 TS 版本；删除 `apps/desktop/` 孤儿 lockfile。
4. 建单一配置模块（Python `config.py` / TS `readConfig()` 已是雏形），端口、SSE、开关只在此定义；删除或重命名 `.env.windows` 为 `.env.example` 并同步实际值。

### 第 3 步：完成前端迁移（2–3 天，收益最大）
1. 确认 Workbench 栈为唯一主线，为旧 ChatView 的每项能力建立新栈对应点后，删除 `views/ChatView.vue`、`components/agentos/Acg*`、`components/federated/`、`KnowledgeGraphView.vue` 及零引用 utils。
2. 合并三套 Run Inspector 为 Workbench 贡献点一套；把 IPC 契约三处手工镜像（ipc-contract.ts / preload.ts / bridge.ts）改为共享类型包或生成脚本。
3. 拆分 `ChatView.vue`（4824 行）、`MissionWorkspaceView.vue`（1508 行）为组合式组件 + composables，不再是巨型 SFC。
4. 清理 `features/acg` ↔ `features/mission` 的反向 import（`features/mission/policy.ts:4`），统一启动请求构造入口。

### 第 4 步：仓库瘦身与 CI 扩容（1 天）— ✅ 已完成
1. `git worktree prune`，移除 4 个陈旧注册 + 6 个孤儿目录；释放约 12 万文件。
2. `papers/` 加入 `.gitignore`，仅保留 `README.md` 与 `RESEARCH_OVERVIEW.md` 等索引；已跟踪文件用 `git rm --cached` 移出索引（本地保留）。
3. 清理 `papers/**/.build/` 已跟踪构建产物。
4. CI 增加 `pytest TEST/tests -q`、`apps/agent/tests`、frontend vitest；把已知 11 failed / 3 errors 变成可见的红灯再逐个修复。

## 五、竞赛视角的额外建议

项目参加挑战杯（XH-202631），评委看到的是可运行演示 + 材料质量，不是仓库整洁度本身。因此：

- **优先级取舍**：第 1、4 步收益最高（"按 README 能跑起来" + "演示环境干净"），第 3 步对答辩演示的视觉一致性影响最大。第 2 步可在答辩后做。
- **不要为整洁牺牲叙事**：迁移报告、审计链是"工程严谨性"的证据，答辩时有用。建议**归档而非删除**——统一移到 `docs/archive/` 并保留一份索引，而不是散在 docs/superpowers、docs/audits、apps/agentOS/docs 三处。
- **明确标注完成度**：README 已诚实标注端-边-云 🚧 和 Pack 删除，保持这种诚实；把"哪些是 live 验收未做"列成清单，比含糊地说"已完成"更专业。

---

## 六、第二轮复查新发现（v2 核心增量）

第一轮未覆盖的盲区：后端/桌面端内部代码、内核遗留与测试健康度、文档声明与实现一致性。以下均为本轮实测。

### 新 P0：实时 ASR 的 WebSocket 端点缺失（功能契约断裂）

- 前端 `apps/frontend/src/services/api/realtimeAsr.ts:29` 已实现 WS 客户端 `websocketUrl('/ai/realtime-asr/${sessionId}')`，被 `components/VoiceRecorder.vue:148` 实际调用。
- Electron 打包下该 URL 解析为 `ws://127.0.0.1:18080/ai/realtime-asr/...`，打到 TypeScript 后端。
- 但 `apps/backend/package.json` 依赖只有 fastify / multipart / pg，**没有 `@fastify/websocket`**；`apps/backend/src` 全量扫描无任何 `upgrade` / WS 处理。Fastify 的 `/ai/*` 是普通 HTTP 通配代理，不接管 Upgrade 请求。
- 最有力证据来自前端自己：`apps/frontend/vite.config.ts:190-192` 注释写明 `ws: true` 后紧跟 `// Availability still requires a corresponding TypeScript WS endpoint.`
- **结论**：前端语音输入的实时识别在 Electron 下拿不到后端服务。修复方案二选一：后端加 `@fastify/websocket` 并代理到 Python ASR；或前端改走已有的 HTTP 多模态接口 `/ai/multimodal/document`。

### 新 P1：后端内部

1. **迁移"建了又删"**：`V4__create_user_feedback_table.sql` 建 8 个对象，`V13__drop_user_feedback.sql` 全部 DROP；`V6__upsert_builtin_roles.sql` 插入 4 个内置角色，`V10__delete_builtin_roles.sql` 一句 DELETE 全删；`V1` 已建 `password_hash`，`V3` 又在全新库上空跑一次 ADD COLUMN。连带 `roles.stable_key` 失去意义（`platform.ts:161-167` 创建/更新角色从不写它，但 `roleWire()` 仍在 API 暴露恒为 null 的字段）。新库初始化承担无谓 I/O，应压缩迁移链。
2. **冗余索引**：`V1` 的 `username/email UNIQUE` 已自动建唯一索引，`V2` 又建非唯一 `idx_users_username`/`idx_users_email`；`messages(conversation_id)` 被 V1/V2/V9 三次以左前缀重复覆盖。
3. **`gateway.close()` 重复注册 3 次**：`app.ts:123`、`gateway.ts:268`、`gateway.ts:269` 都挂到根 app（close 幂等，不出错但冗余）。
4. **重复路由别名 8 组**：`/health/live` vs `/api/health/live`、`/api/chat/text` vs `/ai/chat/text` vs `/api/ai/chat/text`、`/api/users/me` vs `/api/user/profile` 等，部分已无调用方（如 `/api/roles/builtin` 恒返回空）。
5. **丢弃的契约参数**：`chatExecutions.ts:179` 的 `void after` —— 前端 `executionStream.ts:38` 明确传 `?after=${cursor}`，后端 `chat.ts:155-157` 也校验，但 `follow()` 里直接忽略。
6. **跨应用编译期耦合**：`platform/api.ts:1` 直接 `import '../../../backend/src/shared/runtime-defaults.json'`，`services/api/chat.ts:13,69` 用 `import('../../../../backend/src/shared/chat-stream/index.mjs')` 做类型引用——前端构建依赖 backend 源码目录，破坏独立构建边界。

### 新 P1：内核遗留与结构

1. **`SkillEvolutionService` 是纯占位服务**：`apps/agentOS/src/components/evolution/skill_service.py`（48 行）4 个方法全部 `raise NotImplementedError`，带 TODO，全仓仅自身定义/`__all__`/懒加载导出引用，**无任何生产或测试调用**。是"13 部件"里唯一实质空壳。
2. **orchestration 层巨型文件**：`runtime/orchestration/workflow.py` **2808 行**（单个 `RuntimeApplication` 类独占约 2580 行、92 个方法），`acg_execution.py` 2041 行，`storage/repositories.py` 1852 行。workflow.py 混合规划门控、图物化/激活/交接、执行、许可多职责，最该拆分。
3. **遗留兼容分支集中在 orchestration**：含 legacy/兼容/临时语义注释 48 处、33 文件，其中 `workflow.py` 7 处、`acg_execution.py` 4 处，是 11-16 收敛后的"双轨读取路径"，下一轮优先清理区。
4. **可清理的死代码约 15+ 符号**：`recovery/classifier.py:6 classify_failure`、`memory/compression.py:6 compact_record`、`memory/lifecycle.py:8 is_expired`、`mission/algorithms.py:4 task_complexity`、`planner/task_structurer.py:4 structure_tasks`、`auditor/structural.py:4 missing_required_fields`、`auditor/policy.py:4 policy_outcome`、`auditor/quality.py:4 quality_passed`、`resource/domain/algorithms.py:19 ema` 等均全仓 0 调用；另有孤立 Protocol `AuditSink`、`PrivacyMechanism`、`ManagedToolLauncher`。`apps/agentOS/service/agents/` 只剩 `__pycache__`（空壳目录）。
5. **scheduler 部件极薄**：仅 3 文件 74 行纯函数，功能面窄，可评估与 executor 合并（但当前设计自洽，非缺陷）。
6. **测试树健康**：`TEST/tests` 下 293 个 .py；AST 精确统计 `pytest.skip` 1 处、`@skip`/`skipif` 0、xfail 0、空测试 0、模块级 skip 0。`15` 处 `importorskip` 集中在 5 个 SAFE 集成文件（缺可选依赖时跳过，合理）。v1 提到的 `examples.contract_review` 缺失**已修复**（迁至 `TEST/fixtures/contract_review.py`，449 行）。注：本机实测 collect 因缺 `agents`（OpenAI Agents SDK）有 76 errors，非代码缺陷，CI 已通过 `requirements.dev.lock` 安装该依赖。

### 新 P1：磁盘垃圾 `apps/desktop/electron/%SystemDrive%/`

两个各 172KB 的 `.bin` 文件：`%SystemDrive%/ProgramData/SogouInput/Components/Picface/Cloud/sgim_picface_cloud{,_bak}.bin`，是**搜狗输入法云词库**，与项目无关。成因是某脚本把 `%SystemDrive%\...` 环境变量当字面相对路径创建了整棵目录树。全仓 grep 零引用，未被 git 跟踪（被 `*.bin` 规则忽略），可直接删除整个目录。

### 新 P2：文档与实现不符（3 处硬伤 + 1 处内部矛盾）

1. **测试数字偏低**：`README.md:13` badge 与 `:247,:315` 写 `1730 cases`；实测 `TEST/tests` 约 **2353 collected**（293 个 .py、2301 个 `def test_`、505 个 parametrize）。数字应更新或改为"以 CI 结果为准"。
2. **节点/边类型数量不符**：`README.md:75` 声称 6 种节点（Step/Agent/Skill/Memory/Evidence/Control）+ 6 种边；实际 `contracts/acg/schema.py:17-24` 的 `NodeType` 只有 `STEP`/`CONTROL` 两个枚举，EdgeType 只有 `DEPENDENCY` 一个。Agent/Skill/Memory/Evidence 已降级为 StepNode 的 `step_type`/`capability` 字段（schema.py:160,168）。**这是设计演进后文档没跟上**——要么改文档，要么恢复一等类型。
3. **许可证错误**：`LICENSE:1-7` 是**木兰宽松许可证 MPL-2.0（MulanPSL2）**，含专利授权与专利诉讼终止条款；但 `README.md:14` badge 与 `:319-321` 写 MIT。属明确法律文档错误，必须改 README（或改 LICENSE，但需团队决策）。npm 依赖侧无纯 GPL 风险（仅 jszip 双许可可选 MIT）。
4. **README 内部矛盾**：赛题矩阵 `README.md:139` 把"中间决策过程与推理轨迹展示"标 ✅，路线图 `:303` 却把浏览器级 `WAITING_REVIEW → approve → resume` 标 🚧。两处需统一口径。

### 未发现问题的部分（复核确认健康）

- 后端、桌面端、terminal 源码中 TODO/FIXME/HACK/XXX **命中为 0**；内核 494 个 .py 仅 25 条 TODO、0 个 FIXME。`ZHIYI_BACKEND_TS_*` 环境变量是 README:186 声明的有意兼容接口，非遗漏。
- `apps/terminal`（node-pty PTY 服务）与桌面终端是"服务 + 传输层"协作，非重复。
- 两套数据库（PostgreSQL 平台库 7 张表 / SQLite 内核库 20+ 张表）表名零重叠，无 schema 冲突；密钥未被 git 跟踪、无硬编码 sk- 口令。
- `runtime/compatibility/` 仅 2 文件 1KB，`ExecutionEngineMigratingError` 仍是活跃守卫（5 处生产引用），不能删；只有 `__init__.py` 的 RunLock 再导出是冗余转发。

## 七、v1 事实错误修正记录

| v1 表述 | 修正 | 实测证据 |
| --- | --- | --- |
| "CI 只有 backend-ci.yml 一个 workflow，只跑 backend" | ❌ 错误。实际有 `application-ci.yml`（101 行），覆盖 Python 内核/应用/原生启动器、frontend 双构建+测试、desktop/terminal/hands/compact 四包 typecheck+test，以及仓库卫生检查 | `.github/workflows/` 下两个文件；已亲自核对全文 |
| "LICENSE 是 MIT" | ❌ 错误。实际为木兰宽松许可证 MPL-2.0；MIT 只在 README badge/段落出现 | `LICENSE:1-7`、`README.md:14,321` |
| "迁移完成一年后兼容层" | ❌ 措辞不当。`ExecutionEngineMigratingError` 自 2026-08-13 引入、最后改动 2026-11-16，实际约 3 个月 | git 提交 `d39f205a` |

## 八、第三轮行动建议（按投入产出排序）

1. **修 3 处文档硬伤**（30 分钟，零风险）：badge 测试数、节点/边类型描述、MIT→木兰。这三处对外可见度最高，答辩材料也可能引用了错误数字。
2. **补实时 ASR WebSocket 端点**（半天，唯一新 P0）：决定走 WS 代理还是 HTTP 接口，让语音输入在 Electron 下真正可用。
3. **清 `%SystemDrive%` 垃圾目录 + 压缩后端迁移链**（1 小时）：删目录零风险；迁移链压缩需保证已有库兼容检查不受影响（`platform_database.py` 只在空库执行迁移）。
4. **拆 `workflow.py`（2808 行）与清 15+ 死代码符号**（1–2 天）：纯内部质量，不阻塞答辩，可放到赛后。
5. **统一 README 内部口径**（15 分钟）：矩阵 ✅ 与路线图 🚧 对齐。
