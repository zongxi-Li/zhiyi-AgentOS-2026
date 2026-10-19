# PR-S03-02C1-FIX 第二轮独立代码级验收

日期：2026-10-19。结论：**ACCEPT（限明示支持范围）**。原 REJECT 的 1 项 P1 与 2 项 P2 均已独立复验关闭；本轮新增对抗反例未发现任何已支持入口在可信读权限撤销后仍能读取受保护正文，亦未发现恢复预检副作用或下载标识不一致的回归。内核执行/恢复语义未变。本结论基于独立构造的 28 项对抗验证与全路由扫描，不因 1814 项原有测试通过而自动给出。

## 1. 精确 Git/源码基线

- HEAD：`9921a75cf6cfff46388f923795c3878b9aa072cc`（B2 冻结提交），入场与收尾两次核验一致，全程未移动。
- 暂存区为空。工作区 tracked 修改 3 个：`apps/agent/app/api/agentos_v2.py`、`apps/agentOS/src/runtime/planning_loop.py`、`scripts/freeze_gate.py`；untracked 为 3 份开发记录、`apps/agentOS/src/examples/`、2 个新测试文件与被忽略的 `tmp/`。与任务书入场描述一致，无预期外修改。
- 摘要独立复算（算法自行重推导：src/tests 下 .py 原始字节逐文件 SHA-256，仓库相对 POSIX 路径排序，LF 连接 `路径 摘要` 无尾 LF，对 UTF-8 清单再取 SHA-256）：
  - src/tests 438 文件：`bcdd603ad829d08338a459a91319f22a0fd839681f9f5d45ef7d93e8efba0f97`
  - 应用 API：`b78ffdd8d0b1c004f9befdd63c7372070cf9a733c244f86591328897791ccc21`
  - freeze_gate：`bceba8893df4c99f34908d2cb91f7b616922c56d5768b3100f7841cf83783d9c`
- 三组摘要与任务书逐字一致；**全部测试结束后再次复算仍逐字一致**。
- 内核语义未变证据：`git diff HEAD --stat -- apps/agentOS/src apps/agentOS/tests` 仅 `planning_loop.py +5`（C1 的 `observe_progress` 可信宿主接缝，第一轮验收已独立覆盖，FIX 未再改动）；Planning Commit、Safe-Cut、Materialization、Activation、Handoff、Permit、ResourceBinder、NodeRunner、Receipt、Checkpoint、PermitRecovery 无任何 tracked 变更。FIX 实际改动 = 应用 API 查询授权、样例 `_preflight_resume`、新增回归测试与 freeze_gate 映射，与其实施记录第 1 节声明吻合。
- 独立对抗探针：`tmp/c1_fix_audit/test_fix_independent.py`（SHA-256 `5a1eed15e0f77bbe620db74e55014212f37bc633e455751c37977d869397769b`），位于 testpaths 之外，不进入全量收集；未修改生产实现、既有测试、断言、超时或选择规则，未触碰业务数据库。实施记录的 SELF-TESTED 未作为本轮证据。

## 2. 原三项缺陷逐项结论

### F1 / P1 正式读权限撤销后正文可读 —— 已关闭

源码链：`agentos_v2.py:744 require_current_mission_read` 每请求调用 `MissionSemanticService.get_effective_snapshot`，其内部 `_require_access`（semantic_service.py:24）要求 `authorize(...) is not True` 即抛 `PermissionError`→403，仅显式 True 通过；主体只来自 `InternalServiceAuthMiddleware` 校验后的可信上下文（internal_auth.py:50）。`load_content_run`（:767）= 只读 `load_run`（owner/tenant + 软删除 404）+ 正式读核验；带 `missionIntentBasis` 的正式 Run 在服务缺失时 `required=True`→503，不降级。

独立对抗矩阵（同一样例真实完成 Run、真实 sealed Artifact、生产 router + 中间件、同线程 ASGI 直调）：

| 场景 | 结果 |
|---|---|
| 授权基线：8 类正文/元数据入口 | 全 200，两种 ID fragments 内容一致，下载字节与 checksum 相等 |
| 撤销（authorize→False） | artifacts 列表/元数据/fragments/download（两种 ID）、outputs、materials、workspace **全 403**；legacy-outputs 404 |
| 恢复授权 | 同一客户端内 200 恢复，再次撤销复归 403 |
| 服务缺失 / RuntimeError / sqlite 错误 / authorize=None | 上述全部正文入口 **503**（fail-closed，见 §4 边界 1） |
| Workflow 软删除 + Identity 投影滞后 | 全部直达正文入口 404 |
| 跨 Run、跨 user、跨 tenant、无 token、无 actor、无 tenant | 401/403/404，响应无正文标记 |
| 缺失/未封存/归属错误 Manifest | 404；改写 Artifact origin 被 identity 库不可变触发器直接拒绝 |
| 撤权下全 router GET 扫描（37 路由） | 正文与语义入口 10×403，legacy-outputs 与不存在资源 4×404，能力缺失 2×503；21 个元数据通道 200 但**无一包含 sealed 正文标记** |

### F2 / P2 无效恢复创建数据库 —— 已关闭

`contract_review.py:162 _preflight_resume` 位于全部 Store 构造（:234-245）之前：8 个正规库文件 + 拒绝符号链接与未结算 rollback journal；仅复制 DB 及现有 WAL 到临时目录，`mode=ro + query_only` 检查副本；副本产生的 WAL/SHM 只在临时目录清理。独立构造 13 种输入（marker-only、缺库、空库、缺表、缺列、错误 Identity 版本、错误 marker、未结算 journal、损坏 SQLite 头、无 marker 目录、3 类缺索引由 FIX 测试覆盖、WAL-only 正例），全部在「构造即失败」的投毒构造器之前拒绝，源目录前后逐文件 SHA-256 相同。WAL-committed 结构（主库缺失 `content_fragments`、仅存在于 WAL）通过预检且源目录不变，随后真实 `open_runtime` 恢复成功。

### F3 / P2 Artifact ID 下载 KeyError —— 已关闭

下载与 fragments 均使用已授权解析结果的 `manifest["manifestId"]`（agentos_v2.py:2686、2817）。应用内 `read_page/stream_assembly` 仅此两处调用，无其他将 Artifact ID 直传 ContentStore 主键的路径。两种 ID 下载 200、字节逐字一致、SHA-256 等于 Artifact checksum；未知/跨 Run 404、撤权 403。StreamingResponse 异常（流开始后抛错）不被吞成 200，授权错误先于流创建出现。

## 3. 全部正文读取入口及授权链

| 入口 | 授权链 | 撤权实测 |
|---|---|---|
| GET /runs/{id}/artifacts | load_content_run | 403 |
| GET /runs/{id}/artifacts/{mid}（两种 ID） | load_content_run → Identity binding（origin/sealed/kind 复验 + 二次 load_content_run）→ 回退 require_manifest_access（run 归属再 load_content_run） | 403 |
| GET …/fragments、…/download | 经 get_artifact 全链 + 解析后 manifestId 读正文 | 403 |
| GET /runs/{id}/outputs/{ref} | load_content_run → require_run_access / outputRefs 归属 | 403 |
| GET /materials/{mid} | require_manifest_access → run 归属走 load_content_run | 403 |
| GET /missions/{mid}/workspace | require_current_mission_read + require_mission_access | 403 |
| Identity 投影产物（attempts/step-executions 等） | owner 门禁元数据，含引用不含正文 | 200 无正文 |
| /runs/{id}/trace、/events、/context-packs、/copilot 等 | owner 门禁元数据（事件 payload 仅生命周期字段；context 仅有界摘要） | 200 无正文 |
| /runs/{id}/legacy-outputs | load_run（owner）；仅服务无 outputRefs 的历史形状 Run | 正式 Run 恒 404 |

`MissionSemanticService` 确认为唯一正式读取授权来源：授权结论不缓存，`get_output`/fragments/download 每请求重验；执行侧 Guard 与 Permit 语义未动。

## 4. 新发现的绕过路径与独立失败反例

本轮未发现可判 P1/P2 的新缺陷。四项边界观察（均已定性，不阻断）：

1. **语义服务整体缺失时 workspace 仍返回 200（仅元数据）**。`require_current_mission_read` 默认 `required=False`：服务为 None 时 workspace 降级走 identity owner 检查，返回 run 摘要、artifact 元数据与 mission.md 概览；**全部 sealed 正文入口仍 503**。该行为与 B2 冻结 HEAD 完全一致（FIX 前后代码形状相同），非本次引入，且不泄露正文（workspace.py:620 起 artifact 条目仅含 contentRef/checksum 等元数据）。建议后续对带冻结语义的 Mission 将 workspace 也置为 required，统一降级语义。
2. **legacy-outputs 仅在直接数据库手术下可达**。正式内核 Run 每完成一步即写入 `execution_state.outputRefs`（graph.py:601），该端点恒 404；通过 Store API 改写为 legacy 形状（删 outputRefs、植入 step.output）被 durable activation head 不变量拒绝（"permitted completed prefix changed: outputRefs"）。仅在绕过 Store 直接改 workflow.sqlite3 payload 后，撤权状态下该端点返回内联 step 输出（200），而 ValueStore/artifact 入口仍 403。此路径不可经 Runtime 构造，属 owner 门禁的既有兼容通道，建议下阶段评估是否对带 basis 的 Run 一并挂正式读核验。
3. **流开始后的撤权不可撤回已发送字节**。授权在 StreamingResponse 构造前完成并每请求重验；一旦响应开始流式发送，mid-stream 撤销不能回收已下发内容。与 FIX 实施记录第 7 节声明一致，属明示边界。
4. **符号链接拒绝仅源码级验证**。`_preflight_resume` 的 `is_symlink` 检查（contract_review.py:164、177）存在且先行，但本机无符号链接特权（WinError 1314）无法实测构造，本轮记录为环境限制而非通过证据。

正向加固证据：identity 库对 `artifacts` 表的不可变触发器使「改 origin_run_id 指向他人 Run」的篡改直接 IntegrityError；activation head 不变量防 outputRefs 收缩——两层均为本轮独立撞出并确认。

## 5. Runtime 纵向恢复及交付证据

第一轮 62 项集（含真实 Windows spawn 崩溃恢复纵向）本轮重跑全绿：v1 可信 A 执行 → 正式 Graph Revision → Materialization → Activation → Handoff → Permit ISSUED → 子进程 B 后 Checkpoint 提交/Run 未确认时 `os._exit(81)` → 新 Runtime 对账 → 仅调用 C/D → completed；A/B 收据不变、总 Receipt=4 且 committed、GraphVersion=2、AttemptGeneration 正确、canonical Artifact 唯一、HTTP 正文 200 且 checksum 一致。receipt-only、unknown side effect、v1 旧 Checkpoint 恢复 v2、Saga/可信 Retry 等拒绝案例保持原断言（B2 45 项内）。撤权只阻断查询：r3 中授权→撤销→恢复后正文逐字相同，执行事实未被清除；与第一轮「撤权阻断原生派发」形成对照。Planning Commit/Safe-Cut/Activation/Permit/Executor/Receipt/恢复语义零源码变更（§1），无需复验行为级等价性。

## 6. 完整测试结果与源码快照

环境：Windows NT 10.0.26100，Python 3.14.5，默认计时，未用 xdist，空载顺序执行。pytest cwd=apps/agentOS。日志/JSON 均在 `tmp/c1_fix_audit/`（logs/ 与 *.json）。

| 范围 | 命令（cwd=apps/agentOS） | 结果 | 退出码 | 时间 |
|---|---|---|---|---|
| 独立对抗探针 | `python -m pytest -q ../../tmp/c1_fix_audit/test_fix_independent.py --tb=short` | **27 passed / 1 skipped**（符号链接特权缺失） | 0 | 41.53s |
| FIX 36 项永久回归 + 纵向 + 应用 API 兼容 | `python -m pytest -q tests/runtime/test_contract_review_delivery.py tests/runtime/test_kernel_vertical_slice.py ../agent/tests/test_agentos_v2_artifact_api.py ../agent/tests/test_agentos_v2_workspace_api.py ../agent/tests/test_agentos_v2_api.py::test_v2_output_uses_identity_access_without_loading_full_runtime_run --tb=short` | **44 passed** | 0 | 36.51s（21:58→21:59） |
| C1 纵向 / B2 安全 / Workspace 62 项 | `python -m pytest -q tests/components/planner/test_execution_permit.py …test_execution_permit_audit.py …test_permit_recovery.py …test_permit_recovery_final_audit.py tests/runtime/test_kernel_vertical_slice.py tests/runtime/v2/test_workspace_projection.py --tb=short` | **62 passed** | 0 | 137.46s（→22:01） |
| 扩大回归 | `python -m pytest -q tests/components/planner tests/contracts tests/architecture tests/runtime --tb=short` | **1199 passed / 0 failed** | 0 | 1392.88s（→22:25） |
| AgentOS 全量 | `python -m pytest -q --tb=short` | **1814 passed / 0 failed，3 warnings** | 0 | 1407.52s（→22:48） |

三个 warning 为 PyPDF2、Starlette/httpx、Pydantic 弃用提示。36 项永久回归节点数经 `--collect-only` 独立核数一致；旧 4 项缺陷断言（撤权两种 ID、marker-only 建库、下载别名）包含其中且未放宽。全部范围对应同一源码快照：运行前后三组摘要逐字一致，HEAD/暂存区不变。AgentOS 全量不等于完整 API 应用、Java/Vue 全仓测试。

## 7. 尚未验证的生产与并发边界

- 默认生产装配（wiring.py）未启用五 Authority；首次 initial_plan 物化/激活未打通；浏览器 UI、真实供应商模型、远端 Adapter、生产部署未验证。
- 同机规范化 SQLite、受控 OS Fence、首次无控制 DAG v1→v2 范围之外的恢复（控制/循环、任意崩溃切口）保持 fail-closed，未扩大承诺。
- 预检与正式打开之间不支持并发 DDL、文件替换或跨文件原子快照；复制成本随库体积增长，未做大容量基准。
- 服务缺失时 workspace 元数据可见（§4.1）、legacy-outputs 兼容通道（§4.2）、流开始后撤权不可回收（§4.3）、符号链接实测缺环境（§4.4）。
- 跨库联合 CAS、跨机器租约、第三方执行内部副作用撤销不在保证内；规则合同审查不构成法律完整性鉴定。

## 8. 验收决定

**ACCEPT（限明示支持范围：同机、同一规范化 Workflow SQLite、显式装配、受控 Native Runtime、首次无控制 DAG v1→v2、静态目录预检）**。允许 C1 进入冻结流程。

依据：P1（F1）与两项 P2（F2、F3）均经本轮独立构造的反例矩阵关闭，非采信实施记录；37 路由撤权扫描零正文泄漏；恢复预检在 13 种非法输入下零副作用；内核执行/恢复链源码与行为双重未回归。§4 四项边界为既有行为或环境限制，均已披露且不构成「已支持入口的正文读取旁路」，不阻断冻结，建议随下一阶段查询层收口一并处理。本轮仅产出本报告与 `tmp/c1_fix_audit/` 审计工具及证据；未修改生产实现、未改写历史 REJECT、未放宽测试、未创建冻结提交、未 Push/Merge/部署、未改正式 ADR 或业务数据库。
