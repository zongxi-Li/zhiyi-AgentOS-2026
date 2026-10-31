# 知弈 AgentOS 发行版本打包评估

> 评估时间：2026-10-31 13:53–14:20（Asia/Shanghai）
> 评估对象：`C:\Users\LZX\Desktop\kinlin_ai` master @ `1f3d2df9`（工作树有 1 个未提交改动）
> 评估方式：实际构建 + 实机启动 + 门禁实跑，不引用历史文档的数字作为当前结论
> 结论定位：**"壳"已经可打包，但距离"发行版"缺一整层运行时与启动器**

---

## 0. 一句话结论

**今天能立刻产出一个 132.5 MB 的 NSIS 安装包，但它只装了一个浏览器外壳。**
装完之后机器上没有任何东西会去启动 Java 后端、Python 运行时、PostgreSQL、Memurai —— 这些东西现在全部住在仓库和 `%LOCALAPPDATA%\ZhiyiNative`（本机 6.0 GB）里，由 `persistent.ps1 up` 从源码目录拉起。所以现在的产物是**开发环境的外壳**，不是**可以发给别人的软件**。

要出真正的发行版，缺的不是"打包命令"，而是：**运行时随包分发 + 产品级启动器 + 许可证/签名/首启配置**三件事。

---

## 1. 本次实测证据（全部本机实跑）

### 1.1 构建链：通

| 步骤 | 命令 | 结果 |
| :-- | :-- | :-- |
| 前端 electron 产物 | `cd apps/frontend && npm run build:electron` | ✅ 通过（vue-tsc 类型检查 + 2654 modules，20.82s，`dist-electron/` 19.9 MB） |
| Electron 主进程/预加载 | `node build.mjs` | ✅ `dist/main.js` 68.9 kb |
| NSIS 安装包 | `npm run dist` | ✅ 产出 `Zhiyi AgentOS Electron-0.1.0-x64-Setup.exe` **132.50 MB**，`win-unpacked/` **380.8 MB** |

产物指纹：

```
apps/desktop/electron/release/Zhiyi AgentOS Electron-0.1.0-x64-Setup.exe
  size   132.50 MB
  sha256 EE563A512357BD209A861587A1BC24AB66D6F8D7C9E405A73D17160F3B7A4B30
  built  2026-10-31 13:56
```

`app.asar` 24.0 MB / 436 条目：`renderer/` 421、`dist/` 7、`node_modules/` 7、`package.json` 1。

构建期告警（两条都指向发布元数据缺失）：
- `author is missed in the package.json`
- `no code signing certificate configured, signing is skipped`（exe、卸载器、elevate 三处）

### 1.2 打包壳实机启动：通（但踩到一个环境坑）

用独立 `--user-data-dir` + CDP 起 `win-unpacked\Zhiyi AgentOS Electron.exe`：

| 检查项 | 实测结果 |
| :-- | :-- |
| 页面 URL | `kinlin-app://shell/index.html#/login` ✅ |
| 标题 | `登录 - 知弈AgentOS` ✅ |
| 页面 Origin | `kinlin-app://shell` ✅（非 file://） |
| `window.kinlinDesktop` | `object` ✅ 桥在位 |
| `process` / `require` / `global` | 全部 `undefined` ✅ 渲染沙箱生效 |
| 访问本机后端 `GET /auth/me` | `401`（能读到状态码 → 跨源可达）✅ |
| `OPTIONS /auth/login` 预检 | `200` ✅ 登录 POST 通道可用 |
| `GET /actuator/health` | `Failed to fetch` ⚠️（该路径未对壳 origin 放行；壳自身不依赖它，但会误导排障） |
| 真实登录 | 未执行（避免往运行库写入账户数据） |

**环境坑（重要，会误导所有后续测试）**：本机用户环境变量里存在 `ELECTRON_RUN_AS_NODE=1`。带着它，任何 Electron 二进制都会退化成纯 Node 进程，打包版 exe 会**静默退出、退出码 9、连 `userData` 目录都不建、没有任何日志**。清掉该变量后立即正常。N03 的 `up()` 因为只透传白名单环境变量（`SYSTEMROOT`/`PATH`/…）所以一直没暴露这个问题。
→ 发行测试机与验收机必须先确认该变量不存在；启动器应主动剔除它。

### 1.3 测试与门禁：**有一项是红的**

| 套件 | 结果 |
| :-- | :-- |
| Electron 宿主单测 `npm test`（node --test） | ✅ **42/42** 通过（14.4s） |
| agentOS 架构门禁 `pytest tests/architecture/test_capability_upgrade_gates.py` | ❌ **1 failed, 15 passed** |

红灯项：

```
FAILED test_electron_host_does_not_embed_execution_authority
  AssertionError: lsp-client.ts references child_process
```

原因：最近几个 workbench 提交（`49e02578` 起）在 Main 进程里引入了 `child_process`（`lsp-client.ts`、`workspace-search.ts`、`workspace-git.ts`、`workspace-diagnostics.ts`），而门禁仍按 PR-EL-01 的"Main 禁止 child_process"断言。**这是设计契约与实现的冲突，必须先拍板**：要么更新门禁（把禁止面收敛到"执行权威"，允许 LSP/搜索/Git 这类原生能力，并加白名单用例），要么把这些能力挪回 Runtime。发布前不能带着红灯出包。

---

## 2. 现状：两条互不相通的轨道

```
轨道 A（开发/演示，N03 实际路径）
  persistent.ps1 up -Desktop
    → postgres.exe            （deps: %LOCALAPPDATA%\ZhiyiNative\dependencies）
    → memurai.exe             （同上）
    → node tsx apps/hands/hands/service-main.ts
    → python -m uvicorn app.main:app
    → java -jar apps/backend/target/kinlin-backend-1.0.0.jar
    → node apps/frontend/node_modules/vite/bin/vite.js  ← Vite dev server（15200）
    → node apps/desktop/electron/node_modules/electron/cli.js --dev-server=…  ← 源码壳
    → node apps/terminal-host（PTY 服务，注入 KINLIN_TERMINAL_*）
  依赖：仓库目录结构 + JDK21 + Node + Python venv + node_modules

轨道 B（安装包，今天产出的产物）
  NSIS 安装 → Zhiyi AgentOS Electron.exe
    → 从 asar 加载 kinlin-app://shell
    → 直连 http://127.0.0.1:18080（构建期 VITE_API_BASE_URL 烧死）
    → 假设上面那一整条栈"已经在跑"
  依赖：用户自己从仓库跑 `persistent.ps1 up`（且那还会再起一个 Vite + 另一个窗口）
```

两条轨道没有任何衔接：`desktop_shell.py` 只会拼 `node electron/cli.js <repo> --dev-server=…`，没有"已安装 exe"分支；`persistent_runtime.py` 的 `ROOT = Path(__file__).resolve().parents[5]` 把一切钉死在仓库路径上。

---

## 3. 缺口清单

### P0 — 不解决就不能称"发行版本"

| # | 缺口 | 证据 | 影响 |
| :-: | :-- | :-- | :-- |
| P0-1 | **运行时不在包里** | jar 75.4 MB、Python venv 604.5 MB、PostgreSQL 828 MB、Memurai 26 MB、hands `node_modules` 82.4 MB、terminal-host 63.0 MB、JDK 327.9 MB，全靠本机开发环境 | 装到干净机器上，壳打开即白屏/登录必失败 |
| P0-2 | **桌面栈仍是开发形态** | `up()` 起 Vite dev server；壳用 `electron/cli.js --dev-server` | 发行版不该包含 Vite、源码和 CDP 调试端口 |
| P0-3 | **没有启动器/进程守护** | 安装后无人监听 18080；终端服务凭据只由 `terminal_service.desktop_environment()` 注入 | 产品功能缺一半（终端不可用，提示"请通过本地启动入口重新打开知弈"） |
| P0-4 | **Memurai 许可证红线** | README-N03 §依赖准备：Developer 版"仅限开发测试，连续运行最多 10 天" | **直接分发即违规**。必须换 Enterprise 授权，或换 Valkey/Garnet 等 Redis 兼容实现并重验 backend + Lua coordinator |
| P0-5 | **端口硬编码 + 自动杀占用进程** | 15432/16379/18761/18765/18080/18766 固定；`up()` 启动前 `release_ports()` 会停掉占用者 | 用户机器上可能杀掉无关程序；发行版必须改动态端口或改为提示 |
| P0-6 | **首启密钥来源是仓库私有文件** | `init` 默认读 `.secrets/kinlin-win-p1-001/deepseek_api_key`；该目录另有 glm/tavily/jwt/db/redis 等真实密钥 | 发行版没有 `.secrets`；且这些文件绝不能进安装包。需要"首启输 key → DPAPI 保存"或走 UI 模型设置 |
| P0-7 | **架构门禁红灯** | 见 §1.3 | 冻结基线不成立 |

### P1 — 能装但难用/有坑

| # | 缺口 | 证据 |
| :-: | :-- | :-- |
| P1-1 | 未签名 | electron-builder 三处 `signing is skipped`；SmartScreen 会拦 |
| P1-2 | 版本三套 | electron `0.1.0` / backend+agent+frontend `1.0.0` / README 徽标 `1.0.0-candidate` |
| P1-3 | 发布元数据缺失 | `package.json` 无 `author`、无 `license`；NSIS 发布者为空 |
| P1-4 | 产品名带 "Electron" | 快捷方式"知弈 AgentOS Electron"、appId `com.kinlin.zhiyi.electron` |
| P1-5 | 安装/升级/卸载从未实测 | PR-EL-01 登记 BLOCKED，今天仍未补 |
| P1-6 | LSP 依赖没打全 | asar 内 `node_modules` 仅 7 条，只有 `typescript-language-server` 本体，缺 `vscode-languageserver*` 传递依赖 |
| P1-7 | 外部工具依赖 | 工作区搜索优先调 `rg`（有 Node 回退）、Git 视图需 `git.exe`、诊断需 `tsc` |
| P1-8 | API 端口烧死 | `VITE_API_BASE_URL=http://127.0.0.1:18080` 在构建期固化，用户无法改端口 |
| P1-9 | 工作树未冻结 | `ModelRuntimeControls.vue` 402+/203- 未提交；根目录还有未跟踪的评估/修复报告 |
| P1-10 | 无 CI 桌面打包、无校验和清单、无更新通道 | `.github/workflows/` 只有 `backend-ci.yml` |
| P1-11 | 运行时仍按 development 跑 | `environment()` 写死 `ENVIRONMENT=development`；`production` 才会校验 AI internal token |

### P2 — 产品化债（可后置）

- 无自动更新（未接 `electron-updater`，只有未用的 `.blockmap`）
- 无崩溃上报/日志回收；日志只在 `userData\logs`
- 卸载数据策略未定义（`%APPDATA%\Zhiyi AgentOS Electron` vs `%LOCALAPPDATA%\ZhiyiNative`）
- 升级迁移合同：PG 主版本锁 15.19，冷备份/恢复要求"同主版本 + 同 home 路径"
- 无服务化（开机自启、托盘、后台守护）——现在靠人执行 `up`/`down`

### 附：许可证与合规

- `LICENSE` 文件是 **木兰宽松许可证第 2 版**，但 README 与徽标写的是 **MIT** —— 对外发行前必须统一（含 `package.json.license`）。
- 待补第三方声明：Electron (MIT)、Chromium (BSD 类)、PostgreSQL (PostgreSQL License)、Python (PSF)、Node.js (MIT)、Temurin JRE (GPLv2+CE)、Memurai (**商业许可，见 P0-4**)。
- `.secrets/` 内有真实模型与数据库密钥；打包白名单（`dist/**`、`renderer/**`、`package.json`）目前不会带出去，但**仓库整体打包/压缩分享**会带出去，需要显式排除。

---

## 4. 三种发行形态

| 形态 | 内容 | 体积（估） | 工期 | 风险 | 适用 |
| :-- | :-- | --: | --: | :-- | :-- |
| **B 两段式**（今天就可用） | 壳安装包 132.5 MB + 用户自己跑 N03 栈 | 132.5 MB | 0 人日（已产出） | 中高：要求机器已是开发环境；终端/LSP/搜索降级；两条轨道并存 | 内部演示、评委机现场配合 |
| **A 便携整机包**（推荐） | 一个目录/压缩包：壳 + JRE + Python + PG + Memurai + jar + node + 静态前端 + 产品启动器 | 解压 ≈1.6 GB / 压缩 ≈600–700 MB | **4–6 人日** | 中：改动集中在启动器与装配脚本；仍需处理 P0-4 | 比赛交付、内测、离线分发 |
| **C 产品级安装器** | A + NSIS 安装/升级/卸载 + 签名 + 自动更新 + 服务守护 + 授权合规 | ≈1.2 GB | **2–3 周**（不含证书采购与 Memurai 商务谈判） | 高：签名证书、更新服务、数据迁移合同 | 对外商业发行 |

体积测算依据（可验证的数字）：PostgreSQL 828 MB 中 `pgAdmin 4` 独占 683 MB，只留 `bin+lib+share` ≈ **116 MB**；JDK 327.9 MB 经 `jlink` 定制 ≈ **50–60 MB**；Electron 380.8 MB 压成 132.5 MB（实测压缩比 0.35）。主要重量仍是 Python venv（604.5 MB，`kubernetes` 74 MB / `pandas` 64 MB / `chromadb_rust_bindings` 60 MB / `onnxruntime` 42 MB）。

---

## 5. 推荐路线：A（便携整机包）

### 步骤 1｜冻结与立志（0.5 人日）
- 清理工作树（提交或暂存 `ModelRuntimeControls.vue`），删除根目录临时报告
- **拍板 P0-7**：更新架构门禁（推荐：禁止面收敛到执行权威 + 原生能力白名单用例）
- 统一版本为 `1.0.0`；补 `author`、`license`、`productName: 知弈 AgentOS`、新 appId
- 跑完整门禁并留存日志：kernel / agent / backend / frontend / electron / ops

### 步骤 2｜运行时装配（1 人日）
新增 `ops/scripts/release/assemble_portable.py`：
- `jlink` 生成最小 JRE 21（`java.base,java.logging,java.sql,java.naming,java.management,jdk.crypto.ec,jdk.unsupported`）
- Python：**新建**venv（`--copies`）并用 `requirements.lock` + `requirements.native-tools.lock` 以 `--require-hashes` 安装，避免拷贝现有 venv 的绝对路径问题
- PostgreSQL：只取 `bin/lib/share`；Memurai 取 `prepare_persistent_dependencies.py` 已解出的 `memurai.exe`
- 收集：backend jar、`renderer/`、`apps/hands/node_modules`、`apps/terminal-host/node_modules`、`node.exe`
- 生成 `manifest.json`（逐文件 SHA-256 + 来源版本 + 构建时间）

### 步骤 3｜产品启动器（1.5–2 人日）
新增 `product` 模式（复用 `persistent_runtime` 的 DPAPI/端口/日志/备份语义）：
- `--root` 或 `ZHIYI_PRODUCT_ROOT` 取代 `parents[5]`，把所有路径改为"安装目录相对"
- **跳过 Vite**：直接拉起安装目录内的 `Zhiyi AgentOS Electron.exe`（无 `--dev-server`，无 CDP）
- `desktop_shell.desktop_command()` 增加 packaged 分支
- 动态端口（或占用即提示），**默认不再杀进程**；启动前剔除 `ELECTRON_RUN_AS_NODE`
- 首启流程：生成 DPAPI 凭据 → 引导输入模型 Key（或复用 UI 模型设置）→ `init` → 拉起全栈 → 打开窗口
- `ENVIRONMENT=production` + AI internal token 校验路径实测
- 单实例、托盘菜单（启动/停止/日志/备份/退出）、`down` 与 uninstall 的数据保留策略

### 步骤 4｜干净机验收（1 人日）
Windows 11 干净 VM（**不装** JDK/Node/Python/PG/Memurai）：
1. 解压/安装 → 首启 → 输 key
2. 注册/登录 → Mission → Run（真实模型）→ SSE 事件
3. 桌面功能：终端面板、工作区搜索、Git 视图、LSP 跳转、文件对话框、拖放
4. 关闭 → 再启（复用同一 home，不重建库）
5. `down` → 冷备份 → `restore` → `up`
6. 升级覆盖安装 → 数据留存；卸载 → 数据保留策略符合声明
7. 产物校验：`manifest.json` 逐文件比对；安装包 SHA-256 回执

### 步骤 5｜交付材料（0.5 人日）
- `RELEASE-NOTES.md` / `README-发行版.md`（前置条件、安装、首启、故障恢复）
- 第三方许可声明 `THIRD-PARTY-NOTICES.md`
- 已知限制清单（端边云仅位置选择、Memurai 授权、未签名等）

---

## 6. 复现命令（本次评估所用）

```powershell
# 1) 前端 electron 产物
cd apps/frontend; npm run build:electron

# 2) 壳与安装包
cd ../desktop/electron; npm test; npm run dist

# 3) 架构门禁
python -m pytest apps/agentOS/tests/architecture/test_capability_upgrade_gates.py -q

# 4) 打包壳实机验证（注意先清 ELECTRON_RUN_AS_NODE）
Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
& "apps\desktop\electron\release\win-unpacked\Zhiyi AgentOS Electron.exe" `
  --remote-debugging-port=19335 --user-data-dir="$PWD\tmp\pkg-smoke\userdata"
# 另开一个终端读 http://127.0.0.1:19335/json/list，或复用 tmp/pkg-smoke/*.mjs
```

> `tmp/pkg-smoke/` 内本次留下的三个探测脚本（`cdp-check.mjs`、`net-probe.mjs`、`cors-preflight.mjs`）均为只读探测，可留存为后续安装包冒烟用例的种子。

---

## 7. 最终判断（对外发行口径）

> ⚠️ 本节按"对外可分发产品"口径写。若按**内部版（不连带登录、用户自配 API）**交付，请直接看 §8 的范围修订与工时。

- **今天就能交出"能打开的桌面客户端"**：是（132.5 MB，已产出，实机验证过登录页与后端可达）。
- **今天就能交出"别人拿到能用的发行版"**：否。缺一整层运行时 + 启动器 + 许可证处置。
- **按 A 方案做到"便携整机包可交付"**：4–6 人日，主要风险在 P0-4（Memurai 授权）与 P0-7（门禁口径）。
- **按 C 方案做到"商业级安装器"**：2–3 周，另外需要签名证书与 Redis 兼容层的授权/替换决策。

---

## 8. 范围修订：内部版（不连带登录 + 用户自配 API）

> 修订时间：2026-10-31 14:40　触发：交付对象确定为**内部用户**，登录不作为本版功能，用户配置好 API 后即可使用。

### 8.1 这个范围改变了什么

| 维度 | 原评估（对外发行） | 修订（内部版） |
| :-- | :-- | :-- |
| 分发形态 | NSIS 安装器 + 升级/卸载实测 | **便携包（zip / 7z SFX），解压即用** |
| 代码签名 | 阻断项 | 可接受（内部承担 SmartScreen 提示） |
| 自动更新 | P2 待补 | 不需要 |
| 登录 | 保留 | **不出现在界面上**（自动登录，见 8.2） |
| 密钥 | 首启引导 | **用户在产品内 Settings 自配，不再预置** |
| Memurai 授权 | 红线（不可分发） | 内部开发测试可用，但 10 天连续运行上限必须写进说明 |
| 运行时随包 | 必需 | **仍然必需**（这条一分都不能省） |

### 8.2 两个必须先说清的技术事实

**事实一："不需要登录" ≠ "可以关掉鉴权"。**

- `SecurityConfig` 只放行 `/auth/login`、`/auth/register`、`/auth/verify`、health、swagger，其余全部 `authenticated()`；
- `JwtAuthenticationFilter` 还要求 JWT 里的 `sid` 在 `iam_login_sessions` 表有 active 行，否则 401/503；
- `user_id` 贯穿 `Conversation`、`Role`、`UserFeedback`、`local_workspace_authorizations` 以及 Run 访问判定。

所以直接关鉴权会让"归属/授权"整条链失去主体。**正确做法是：首启自动注册一个本地账号 + 自动登录，界面永远不出现登录页。** 登录相关代码保留，用 `KINLIN_AUTH_MODE=local|account` 开关切换，将来要恢复账号体系不用返工。

**事实二："配好 API 就能用"已经实现了一半，但有一个生效边界。**

| 链路 | 现状 | 配置后是否立即生效 |
| :-- | :-- | :-- |
| Settings 页管服务端供应商档案 | 已有：`GET/POST /ai/llm/profiles`、`/profiles/active`、`/profiles/test`（`apps/agent/app/api/llm_admin.py`，前端 `SettingsView.vue`） | — |
| 密钥落盘位置 | `<home>\data\llm_profiles.json`（明文 JSON，目录 ACL 限当前用户） | — |
| Chat | 每请求 `_resolve_system_provider_config()` 读激活档案 | ✅ 立即 |
| ACG Planner / 节点执行 | 模型注册表在**应用装配时**构建（`wiring.build_model_setup` → `AGENTOS_MODELS` → `default_model_binding`），`llm_admin` 只 `get_llm_gateway(refresh=True)`，**不重建注册表** | ❌ **需重启栈** |

本机实证：`%LOCALAPPDATA%\ZhiyiNative\default\data\llm_profiles.json` 里 4 个档案全部是 `key_env=DEEPSEEK_API_KEY` 的 env 种子（无内联密钥），`active=deepseek` —— 也就是说**当前完全依赖启动器注入环境变量**，这正是发行版必须切断的依赖。

结论：内部版只需做到"**用户在 Settings 里填内联 key → 激活 → 重启一次 → 全链路可用**"。重启由启动器一条命令/一个按钮完成，成本可忽略；想要零重启需改代码重建注册表（+1 人日，见 8.4）。

### 8.3 内部版最小闭环（A′ 形态）

```
ZhiyiAgentOS-1.0.0-internal\           ← 解压即用
├─ Zhiyi AgentOS.exe                   ← 打包壳（asar，kinlin-app://shell）
├─ start.cmd / ZhiyiAgentOS.exe        ← 启动器（product 模式）
├─ runtime\  jre\ python\ pgsql\ memurai\ node\ 
├─ apps\     backend\kinlin-backend.jar  agent\  agentOS\  hands\  terminal-host\  local-runtime\
└─ data-home\                          ← 首启生成：DPAPI 凭据、PG cluster、SQLite、workspace
```

首启流程：`start.cmd` → 生成随机本地账号 → `POST /auth/register` → 账号密码进 DPAPI → 起 PG/Redis/Python/Java → 拉起打包壳（不带 `--dev-server`）→ 壳经 IPC 向主进程取会话 token → 前端跳过登录页直接进应用 → 用户去 Settings 填 key → 提示"重启生效" → 启动器 restart → 全链路可用。

### 8.4 工作量（修订后）

| # | 工作项 | 工时 | 说明 |
| :-: | :-- | --: | :-- |
| 1 | 运行时装配脚本（JRE jlink / Python venv / PG bin+lib+share / Memurai / node / jar / renderer）+ 逐文件 SHA-256 清单 | 1 d | 上一轮已把各组件体积摸清（PG 可省 683 MB 的 pgAdmin） |
| 2 | 启动器 product 模式：路径可注入、**跳过 Vite**、直启打包壳、动态端口且不杀进程、剔除 `ELECTRON_RUN_AS_NODE`、`restart` 子命令 | 1.5 d | 复用 `persistent_runtime` 的 DPAPI/日志/备份语义 |
| 3 | 自动登录：启动器注册本地账号 → DPAPI → main/preload 提供会话 → 前端 electron 模式跳过登录页、401 自动重登、隐藏登出按钮 | 0.5–1 d | 主进程持密码、渲染层只拿 token |
| 4 | 配置闭环：启动器不预置密钥；Settings 保存/激活后提示"重启生效"并触发起重器 restart | 0.5 d | |
| 5 | 分发：便携包打包 + README（含 Memurai 10 天上限、无签名、端口占用处理）+ 校验和 | 0.5 d | |
| 6 | 干净机冒烟（无 JDK/Node/Python）：首启 → 自动进应用 → 配 key → 重启 → Chat + Mission 实跑 → 终端 → 重启复用数据 | 1 d | |
| **合计** | | **4–5 人日** | |
| 可选 | 配置零重启（upsert/activate 后重建 model registry + `bind_registered_planner_llm`） | +1 d | 需补运行期重建用例 |

### 8.5 可以放宽 / 不能放宽

**内部版可以放宽**
- 不做代码签名、不做自动更新、不做 NSIS 安装/升级/卸载实测（改为解压即用）
- Memurai Developer 可用（内部开发测试），但必须在 README 写明"连续运行 ≤10 天"且**不得对外分发**
- 单用户、单实例、无多账户隔离

**仍然不能放宽**
- 运行时必须随包（否则干净机器装完不可用）
- 必须切断对仓库 `.secrets` 与开发工具链（JDK/Node/Python/Maven/Vite）的依赖
- 端口策略必须改（默认不能杀用户进程）
- 必须有干净机验收（至少一台没装过开发环境的 Windows 11）
- 冻结基线：架构门禁红灯与未提交改动必须先处理

### 8.6 需要拍板的四件事

1. **API 生效方式**：重启生效（0.5 d，推荐）还是热生效（+1 d）？
2. **认证形态**：自动注册本地账号 + 自动登录（推荐）还是新增一个 loopback + 内部令牌保护的 `/auth/local-session` 端点（更干净，但动安全面，需补契约测试）？
3. **分发形态**：zip/7z SFX 便携包（推荐）还是仍要 NSIS 安装器？
4. **Memurai**：内部先用 Developer（写清限制），还是这次就换 Valkey/Garnet（需重验 backend 缓存与 Lua coordinator）？

---

## 9. 实施进展（2026-10-31 14:20–14:35）

按 §8 的定稿方向开工，第一阶段目标是**先把"运行时能不能真的随包搬走"证死**，再写启动器。

### 9.1 已完成并验证

新增 [`ops/scripts/release/assemble_portable.py`](../ops/scripts/release/assemble_portable.py)，一次装配出便携产品根：

```
D:\build-test\ZhiyiAgentOS-1.0.0\        总 1610 MB（63 秒）
├─ app\          381 MB   打包壳 win-unpacked（asar + exe）
├─ apps\         466 MB   hands 205 / agentOS 108 / backend jar 75 / terminal-host 63 / agent 15
├─ runtime\      785 MB   python 504（解释器 50 + 依赖 454）/ pgsql 116 / node 89 / jre 50 / memurai 26
├─ ops\ scripts\         启动器与 schema 脚本
└─ product.json          版本清单
```

从**装配后的目录**逐项实跑（不依赖本机开发环境）：

| 组件 | 验证方式 | 结果 |
| :-- | :-- | :-- |
| Python | `runtime\python\python.exe -c "import fastapi,chromadb,psycopg"` | ✅ 3.14.5，`sys.prefix` 指向随包目录，依赖全部导入 |
| JRE | `runtime\jre\bin\java.exe -version` | ✅ OpenJDK 21.0.11（jlink 17 模块裁剪，50 MB） |
| Node | `runtime\node\node.exe` + hands 的 `tsx` | ✅ v24.19.0，tsx v4.23.15 |
| PostgreSQL | 随包 `initdb` → `pg_ctl start` → `psql` 查询 → `stop` | ✅ 15.19，`select version()` 正常 |
| Memurai | 随包 `memurai.exe` + 随包 python 的 redis 客户端 | ✅ PING True，memurai 4.1.2 / redis 7.2.5 |
| 桌面壳 | 上一轮已验（win-unpacked 直启，`kinlin-app://shell`，可访问 18080） | ✅ |

### 9.2 这一阶段推翻/确认的三个设计假设

1. **不能照搬 venv**：现有 venv 的 `pyvenv.cfg` 里 `home` 是绝对路径（指向开发机的 Python314），目标机没有它就直接失效。改为"复制 CPython 树 + 整包放 site-packages"后，`sys.prefix` 跟随 exe 位置，实测可搬移；`site-packages` 里唯一的 `.pth`（pywin32.pth）**不含绝对路径**，可以整包搬。
2. **PG 必须瘦身**：原始 828 MB 里 `pgAdmin 4` 占 683 MB，只留 `bin/lib/share` 后是 116 MB。
3. **启动器不能复用 `pg_ctl` 的继承 stdio**：`pg_ctl start` 会让 postgres 子进程继承父管道，导致启动脚本"卡住不返回"。产品启动器必须像 N03 的 `native.spawn` 一样**直接拉起 `postgres.exe` 并把 stdout/stderr 重定向到日志文件**。

### 9.3 下一阶段（按此顺序）

1. `product_runtime.py`：patch `native_runtime.ROOT` 到产品根、改走随包二进制、**不起 Vite**、端口占用只报错不杀进程、`restart` 子命令、生成并注入 bootstrap 凭据与终端凭据。
2. 免登录链路：启动器首启 `POST /auth/register` 建本地账号（DPAPI 保存）→ 壳主进程持凭据换 token → 渲染层拿 token → 路由跳过登录页 → 401 时自动重登。
3. 可配置 API 端口：把后端 origin 从"构建期烧死"改为 preload 下发（`window.kinlinDesktop.apiOrigin`），否则动态端口与静态渲染不兼容。
4. 装配脚本补 `product_runtime.py` 与 `start.cmd`，产出 zip/7z SFX + README（Memurai 10 天上限）。
5. 干净 Windows 11 冒烟：首启 → 自动进应用 → 配 key → 重启 → Chat + Mission → 重启复用数据。

---

## 10. 内部发行版落地（第二轮，2026-10-31 14:20–14:55）

产品启动器、免登录链路与便携包都已跑通，并在**从 zip 重新解压、PATH 只剩 System32** 的条件下完成首启验证。

### 10.1 产出物

```
D:\build-test\ZhiyiAgentOS-1.0.0-internal.zip    553 MB
  sha256 B5C66C1EF823417250A8A6A8C6590DE819352801E1EDDC48071ECCD2BF691FD7
  解压后 1426 MB（含 app-local VC++ 运行库）
  ZhiyiAgentOS-1.0.0\
    start.cmd / stop.cmd / restart.cmd / status.cmd
    app\          打包壳（asar，kinlin-app://shell）
    runtime\      python 3.14.5 · jre 21 · node 24.19 · pgsql 15.19 · memurai 4.1.2
    apps\         backend jar · agent · agentOS · local-runtime · hands · terminal-host
    ops\ scripts\ product_runtime.py 与复用的 native 运行时模块
    README-内部版.md / product.json
```

装配入口：[`assemble_portable.py`](../ops/scripts/release/assemble_portable.py)（约 60 秒出包，7z 压缩约 2 分钟）。
启动入口：[`product_runtime.py`](../ops/scripts/release/product_runtime.py)。

### 10.2 这一轮改的东西

| 文件 | 改动 |
| :-- | :-- |
| `ops/scripts/release/product_runtime.py` | **新增**：product 模式启动器（init/up/down/restart/status/open） |
| `ops/scripts/release/assemble_portable.py` | **新增**：便携包装配 + 扁平化依赖 + zip |
| `apps/desktop/electron/src/main.ts` | 本地会话 bootstrap（用启动器注入的凭据换 JWT）+ 同步下发后端 origin |
| `apps/desktop/electron/src/preload.ts` | 暴露 `apiOrigin` 与 `session.ensure()` |
| `apps/desktop/electron/src/lib/ipc-contract.ts` | 新增两个通道 |
| `apps/frontend/src/platform/electron/session.ts` | **新增**：渲染层免登录入口（含并发去重） |
| `apps/frontend/src/platform/api.ts` | 后端 origin 以 Main 下发为准，构建期常量退居兜底 |
| `apps/frontend/src/router/index.ts` | 路由守卫在桌面壳内先建会话，登录页不再出现 |

### 10.3 验收证据（全部实跑）

| 验收项 | 方法 | 结果 |
| :-- | :-- | :-- |
| 首次启动自动初始化 | 解压后直接 `start.cmd` | ✅ 自动创建 `data-home`，随后 UP |
| 免登录 | CDP 读页面状态 | ✅ `kinlin-app://shell/index.html#/chat`，有 token 与 userId，非 `/login` |
| 动态端口 | 启动器挑整组空闲端口 | ✅ 本机 0 号端口组被 N03 占用 → 自动落到 offset 2（Java 18082），壳内 `apiOrigin=http://127.0.0.1:18082` |
| 端口占用不杀进程 | 代码路径 `occupied_ports()` | ✅ 只报错并给出 PID/进程名 |
| 业务接口 | 页面内用真实 token 调用 | ✅ `/auth/verify` 200、`/conversations` 200、`/ai/llm/profiles` 200 |
| 终端服务 | `GET 127.0.0.1:18768/health` | ✅ `{"status":"UP"}` |
| 配置 Key → 重启 → 生效 | 写入测试档案（无效 Key）→ `restart` → 查模型目录 | ✅ 重启前 `/ai/chat/models` 502（未配置）→ 重启后 200 且 `provider=deepseek`、`model=deepseek-flash`；`/chat/text` 因无效 Key 返回"AI服务不可用"，证明请求确实走的是配置的供应商 |
| 关窗后再开 | 杀掉壳进程 → 再点 `start.cmd` | ✅ 只重开窗口，不重启服务 |
| 停止 | `stop.cmd` | ✅ 7 个服务全部 graceful，无残留进程，端口全部释放 |
| 数据复用 | 同一 home 二次启动 | ✅ 复用同一账号（userId 不变）与数据库 |
| 无开发工具依赖 | `PATH=C:\Windows\System32;C:\Windows` 下首启 | ✅ 全链路成功（PG initdb、Python、Java、Node 全部来自随包 runtime） |
| 依赖布局 | pnpm junction → npm 扁平 | ✅ hands 依赖 82 MB → 17 MB，zip 里不再有重解析点 |
| 干净机的 VC++ 运行库 | 装配时把 vcruntime/msvcp 放到 pgsql/node/memurai 的 exe 旁（app-local） | ✅ 共 9 个 DLL，不依赖目标机预装 VC++ 运行时 |

### 10.4 还没做 / 仍需你这边确认

1. **真实 Key 的 Chat + Mission 冒烟**：机制已验证（配置后重启即被 Planner/执行链路采用），但真正跑通一次对话与 Mission 需要有效 Key。要么你在设置里填自己的 Key，要么授权我用 `.secrets` 里的 Key 在本机跑一遍。
2. **真机干净 Windows 11**：本轮用"PATH 只剩 System32 + 从 zip 解压"模拟，覆盖了"机器上没有 JDK/Node/Python"这一核心风险；但真正的全新虚拟机（无 VC++ 运行库、无中文字体差异等）仍需一次人工验收。
3. **架构门禁仍是红的**（`test_electron_host_does_not_embed_execution_authority`）：你们需要先决定是放宽门禁口径还是把 LSP/搜索/Git 挪回 Runtime；这条不影响运行，但影响"可提交/可发布"的整洁性。
4. **登录代码保留但未删除**：用 `KINLIN_AUTH_MODE=local` 语义隔离，将来恢复账号体系不需要返工。
5. **小瑕疵**：AI 服务启动日志仍会打印"未配置可用的模型 API Key"（它只查环境变量，不查供应商档案），对排障有干扰，建议后续改成查档案。

---

## 11. 第三轮：任务链路定位与会话自愈验证（2026-10-31 16:20–16:40）

这一轮补上"配好 Key 之后任务能不能跑"和"会话过期会不会卡住"两个尚未证实的点。

### 11.1 无 Key 时 Mission 的真实失败形态

在发行包里用与 UI 完全一致的载荷创建任务（`POST /api/agentos/v2/missions`，含 `clientRequestId` / `semantics` / 完整 `input`）：

| 场景 | 结果 |
| :-- | :-- |
| 发行版，未配置 Key | 202 受理 → **0.2–0.6 秒内 run 变 failed**，`lifecycleMessage="ACG 工作流执行失败"`，`failureCode=null`；AI 日志为 `Planning Commit rejected: STALE_STRATEGY` |
| N03 开发栈，有真实 Key | 202 受理 → run 进入 `planning`，持续调用真实模型（>60 秒仍在规划），`failureCode=null` |
| 两侧载荷 | 完全相同（同一份 `buildWorkbenchStartRequest` 形状） |

结论：**失败原因是"没有可用模型"，不是打包缺陷**。机制是 `initial_planning_sources.capture_initial_sources()` 在快照捕获异常时退化成 `initial-source-unavailable-v1` 指纹，随后 `planning_commit` 比对冻结来源失败 → `STALE_STRATEGY`。

> 这是产品体验问题，不是本次发行版的阻断项：**用户先配 Key、再重启、再建任务**就是正常路径。但要如实说明：忘记配 Key 时界面只显示"ACG 工作流执行失败"，看不出原因。建议后续在创建任务页或失败横幅里，按 `/ai/llm/profiles` 的 `source=env` 且无可用档案时给出"尚未配置模型 API Key，请到设置配置后重启"的提示。

### 11.2 会话过期自愈（已验证）

| 步骤 | 结果 |
| :-- | :-- |
| 把 `localStorage.token` 改成无效值，再导航到受保护路由 `#/chat` | ✅ 守卫判定无效 → 清空 → 调用 Main 的 `session.ensure()` 重新登录 → 停留 `#/chat`，`/auth/verify` 返回 `valid=true` |
| 同样的动作在非保护路由（如 `#/missions` 列表） | ⚠️ 守卫不校验，靠接口 401 触发清理；会先弹一次"登录状态已过期，请重新登录"的提示再自愈 |

也就是说：**长时间开着窗口，JWT 过期不会把用户卡在登录页**；只有提示语对"免登录版"不合适（建议后续在桌面壳内抑制这条提示，静默重登）。

### 11.3 对照测试留下的痕迹（已清理）

- 在 N03 开发栈上注册了临时账号 `release_smoke_fixed`（`/auth/register` 是公开端点），用于验证"有 Key 时任务能进 planning"。
- 该账号下的 2 个测试任务已 `cancel` + `DELETE`，没有残留运行。临时账号本身仍在开发库里（如需清理请手动删除该用户）。
- 发行版一侧的 `data-home` 已整体删除，交付 zip 仍是初始状态。

### 11.4 给真机冒烟的预期

1. 填 Key 后必须 `restart.cmd`，否则 Planner/执行链路仍用旧配置（这是 §8 就确定的行为）。
2. 任务创建后**会有较长时间停在"正在规划 ACG 执行路径"**（真实模型规划 1 分钟级别很正常），不是卡死。
3. 若创建任务立刻失败并提示"ACG 工作流执行失败"，第一件事查设置页的供应商是否已激活、Key 是否有效。
4. Java→AI 之间偶发一次 `503 AGENTOS_UPSTREAM_UNAVAILABLE`（本次对照中出现过 1 次、重试即成功），属重试可恢复，不是安装问题。

### 11.5 中文路径问题（已修复，重要）

实测发现 **PostgreSQL 不支持非 ASCII 路径**，程序目录和数据目录都算：

| 场景 | initdb 结果 |
| :-- | :-- |
| `D:\build-test\ZhiyiAgentOS-1.0.0`（ASCII） | ✅ 成功 |
| `D:\agent os test\...`（ASCII + 空格） | ✅ 成功 |
| `D:\发行测试\...`（中文程序目录） | ❌ `invalid byte sequence for encoding "UTF8": 0xb7` |
| ASCII 程序目录 + 中文数据目录 | ❌ 同上 |

处置：启动器在动手前先校验 `程序目录` 与 `数据目录` 是否为纯 ASCII，不是就直接给出可执行提示
（"请把发行包解压到纯英文目录，例如 D:\ZhiyiAgentOS，可以带空格"），不再把 initdb 的原始报错抛给用户；
`README-内部版.md` 的「使用」与「已知限制」两处都写明了这条要求。
