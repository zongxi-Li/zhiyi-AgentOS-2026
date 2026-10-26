# PR-C2B-INT-2E-CLOSEOUT：人工审核策略修复与 V1 最终冻结收束

日期：2026-10-26。裁决：**BLOCKED**（人工审核与 Java 组合修复受限通过；正式冻结门禁仍未通过。估算器完整剖面缺口另按 INT-2E-ESTIMATOR-FIX 修正，不能把定向修复等同于正式门禁通过。详见 §7；不推送、不部署、不改 Gitee）。

## 0. 入场核验

- GitHub 参考基线 `cfe67a1e69711abf00deede0d53ed14dbfaa7928`；本地保留三笔未推送提交 `8b717fcf`（INT-2C/2D 冻结基线）、`113129ec`（交付校验与取消事件恢复边界）、`6192be1a`（V1 真实集成证据与验收阻断）。远程 master 仍为 `cfe67a1e`，祖先关系安全；既有本地修复未被覆盖。
- 入场时工作区仅含本轮修复文件（见 §1/§3/§4 变更清单），无并行会话文件。
- 前序两轮执行曾在测试运行期间继续编辑源码（`source_before != source_after`），造成一次 `ImportError` 与一次恢复路径误报，均为竞争假象；稳定源码下定向复跑通过（`core.midrun-race.log`/`http.midrun-race.log` 保留原始证据）。最终分层重验（§5）全部在源码零漂移下完成。

## 1. A：human_in_loop 正式人工审核策略

### 1.1 反例复现（永久红态）

`apps/agent/tests/test_agentos_c2_human_review.py::test_human_in_loop_is_a_formal_review_barrier_before_final`：以原真实失败场景构造——创建任务选择 `human_in_loop`、Run 保留 `reviewMode=human_in_loop`、正式图三节点均无审核要求、Run 直接完成、Review 列表空。修复前基线上该测试失败（`.tmp-tests/int2e-closeout/human-red.log`，09:05，1 failed）；接入可信策略后通过（`human-green.log`）。

根因：`reviewMode` 仅被保存，未进入正式编译输入。Native 审核屏障会遵守 `requires_review`，但没有任何权威边界把用户显式选择翻译成该标志。

### 1.2 策略合同（`human-review-all-steps-v1`）

- `auto`：不注入策略，保留既有自动审核语义（含既有 descriptor/template 审核门与已显式 `reviewRequired=true` 合同）。
- `human_in_loop`：V1 无法可靠分类自由文本风险，按保守语义要求**每个执行步骤**（含交付物生成）审核；策略含 `policyVersion/mode/scope/source=run.reviewMode/implementationSha256`（策略文件自身指纹）。
- 审核义务只能由服务端可信策略授予/取消；模型候选中的 `user_human_review` 约束与策略冲突时在接受前 `INVALID_PROPOSAL` 结构化拒绝；不可信 Agent 文本不能授予或取消审核义务。
- 策略版本与来源随正式源捕获（`loweringOptions.reviewPolicy`）与编译指纹（`initial_recipe_fingerprint` 收录 `human_review_policy.py`）冻结，可审计且与接受图一致。
- 恢复/图修订：非首次（runtime）规划提交在 `human_in_loop` 下一律 `CONTROL_BARRIER_BLOCKED`（需全新显式接受 Run），不隐式重新解释旧许可；旧 Permit 不能被重新解释为人工审核（`test_old_permit_cannot_be_reinterpreted_as_manual_review`）。
- 前端说明与实际语义一致：人工审核模式描述更新为「每个执行步骤完成后暂停，等待人工审核；最终交付须经批准。」（`CreateMissionView.vue`，spec 断言文案）。

### 1.3 权威边界实现（不新建第二套状态机）

- 注入点：`RuntimePlanningCommitAuthority` 产出候选时 `bind_review_policy`（服务端所有，非模型文本）；接受校验 `validate_review_policy`；编译 `review_lowering_input` 在既有 lowerer 之前决定 typed `review_required`（模板与 ACG 两路同权）。未绕开 TopologyCompiler/Graph Authority，未中途改节点标志，未新建审核状态机。
- 审核决定（`workflow_runtime.py`）：在原 Run 锁内、产生审核副作用（audit/deferred memory）前复核当前写权限（`require_write_access`），审核人取可信主体 `actor_id`，忽略客户端标签；幂等重放同样过权限复核；未授权用户无法提交审核决定。
- 交付发布边界（复用既有终态事实，非新执行状态机）：`artifact_is_public`——正式交付身份仅在 Run `SUCCEEDED` 后公开；`queries.artifacts_for_run`、工作区投影、内容 manifest 读取（含投影间隙的 raw-content 回退，对 human_in_loop 正式 Run 在完成前一概 404）全部收口。批准前内容只能作为审核证据，不能作为最终交付。

### 1.4 永久回归

- HTTP（`test_agentos_c2_human_review.py`，7 项）：人工审核屏障红→绿、auto 不强制暂停、拒绝/取消不触发重执行、旧 Permit 不重解释、策略冲突在接受前 fail-closed、写权限撤销在持久副作用前拒绝。覆盖服务重建、逐步批准、原 operationId 重试、Dispatch replay、批准前 final 不可读（`human-six.log`、`human-final-pre.log` 7 项、`human-lifecycle-green.log` 4 项）。
- 策略内核（`test_human_review_policy.py`，2 项，`@freeze_gate`）：模型约束不能取消用户策略；初始策略冻结且 mode 漂移不被重解释。
- 组合内（`initial_planning_sources`/`planning_commit_runtime`/`graph_revision_commit`/`workspace_projection`/`contract_review_delivery` 等，见 §5 L2）。

真实浏览器人工审核流程验证见 §5 L6。

## 2. B：113129ec 安全修复独立复验

逐项独立审阅未推送提交 `113129ec` 差异（非仅复跑）：

1. sealed canonical final 损坏：下载端点先在有界 `SpooledTemporaryFile`（1MB 内存阈值）内完成装配与 `byteLength` 核对，验证通过才发送 HTTP 200/任何字节；聚合 checksum 由原 Store 在装配末端校验。损坏一律 503 `Artifact content integrity unavailable`，不返回未验证正文。
2. Fragment/聚合 checksum/byteLength/unsealed：页面读取路径校验 `sealed` 标志与逐片段 sha256+长度。
3. 下载失败不泄漏存储内部细节：统一 503 泛化文案。
4. Coordinator 首次调度前取消：shutdown 取消并 gather 后，在 `_accepting=False` 保护下于锁内清理已 settled 的 Task 句柄，无残留执行槽（取消先于协程首跑时不进 finally 的边界已注释说明）。
5. SSE EOF/重连/序号重置/终态：`RuntimeEventClient` 连接纪元开始时 `lastSequence=-1`（瞬态流跨纪元不判序），干净 EOF 经 finally 重连（未中止且非终态），401/403 断开等待新会话显式重连，终态不重连，重连定时器在 disconnect 清理。
6. SSE 重连绝不发送新 Dispatch：客户端只观察（GET 流），无任何执行命令提交路径（结构性保证）。
7. 刷新/重登录/恢复不产生重复节点或 Artifact：`runtimeEvents.spec.ts` + 服务端幂等/重放回归（§5 L1/L2 内 `dispatch_http`、`runtime_live_events`、`final_delivery` 等）。

性能限制如实保留：`SpooledTemporaryFile` 1MB 阈值后落盘，大文件容量与延迟未验收，不据此宣称大文件容量已验收；未引入新 Artifact Store 或 SSE 持久消息系统。独立复验未发现新 P0/P1。

本轮续跑中发现并限定修复的相邻缺陷：human_in_loop 正式 Run 在末节点获批前 canonical final 已可经交付投影/内容回退读取（§1.3 第三点），已随本策略边界一并收口并进入永久回归。

## 3. C1：Java SSE 计时测试

原失败：`AiSseGatewayServiceTest.idleTimeoutResetsOnEventsAndIsDistinctFromMaximumDuration`，组合两次 52/53，25ms 心跳/80ms idle/70ms maximum 的真实墙钟断言在调度抖动下不稳。

定性：测试依赖真实墙钟（loopback+CPU 抖动），非实现错误——生产代码 `timeout(idle)` 语义与 absolute maximum 语义本身正确。修法：

- 生产代码抽出 `withTimeouts(body, clock)`（包内可见），两钟（idle timeout 与 maximum delay）共享显式 `Scheduler`；生产路径不变（`Schedulers.parallel()`）。无行为变化。
- 测试改用 `VirtualTimeScheduler`+`StepVerifier.withVirtualTime`：保留原 25/80/70ms 场景，并加强——40ms idle 必须在 25/50ms 心跳处刷新、absolute maximum 仍在 70ms（而非 2×idle）终止；另断言无事件时恰在 idle 边界触发 `SSE_IDLE_TIMEOUT`。
- 未增加睡眠、未删用例、未放宽断言、未跳过；`pom.xml` 增加 test-scope `reactor-test`（不进生产依赖）。
- 完整组合结果见 §5 L3（同一最终源码快照，真实退出码）。

## 4. C2：正式冻结门禁预算预检

### 4.1 只读诊断（历史证据）

门禁预算 300s 为墙钟硬执行（超时即 `INCOMPLETE_TIMEOUT`/`INCOMPLETE_GATE_BUDGET_EXCEEDED`，完整性测试钉死「墙钟超预算永不成功」）。预检把 `tmp/freeze_gate/test_durations.json` 中**各测试历史最大值求和**当作本次运行的预估，且该缓存只涨不降（`max()` 棘轮）：

| 时间（UTC 报告） | 状态 | 真实墙钟 | 预检估算 |
| --- | --- | --- | --- |
| 10-25 04:03 | PASSED（284 节点） | 191.851s | 285.49 |
| 10-25 04:48 | BLOCKED_KNOWN_DURATION_OVER_BUDGET | 未启动 | 320.9 |
| 10-25 04:50 | PASSED（295 节点，缓存人工清空后） | 191.718s | 0 |
| 10-25 08:02 | INCOMPLETE_TIMEOUT（300 节点，负载期） | 300.657s | 213.64 |
| 10-26 00:01 | PASSED（302 节点） | 273.989s | 287.6 |
| 10-26 00:26 | BLOCKED_KNOWN_DURATION_OVER_BUDGET | 未启动 | 315.82 |

系统性偏差实锤：同一选择真实墙钟 155–279s，而每通过一轮，混合不同运行（多含负载期）的逐测试最大值之和就把下一轮预检顶过预算——门禁自我砖化，10-25 曾以清空缓存恢复（当时定性=新克隆等价；本轮任务明确禁止清空）。预检剩余预算 289.94s < 估算 315.82s，pytest 无法启动。

### 4.2 历史改动及独立复验修正

`4886c518` 中的估算器保存了逐测试 `max/last`，但没有同一次完整运行的身份或提交边界。该历史实现不能称为“最近完整运行剖面”：不同运行的 last 可以拼接；实际超时报告 durations 为空，缓存 last_count=0，不能推导超时必然阻断下次启动。原 42 项测试及 300.79 秒超时结果保留为历史证据，不作为新合同的通过证明。

后续 [INT-2E-ESTIMATOR-FIX](INT-2E-ESTIMATOR-FIX.md) 采用同一源码摘要、同一 node manifest 的最近完整剖面：结构化记录真实 collection 和全部节点三阶段耗时，完整成功、无超时/源码漂移时才原子发布；任何缺失/不匹配明确为 UNKNOWN，不能把未知当零。旧 max/last 仅保留为历史，不拼接估算。估算器修复和正式冻结门禁通过是两件事。

历史正式门禁仍为 **INCOMPLETE_TIMEOUT，498 节点、300.79 秒、exit 1**。498 节点和约 430 秒线性外推不能证明 300 秒预算必然不可满足，只能确认这次在该环境下超时。后续可限定诊断测试装配/运行开销，或另行裁决门禁策略；本次不改 300 秒预算、固定 manifest 或测试映射，不重跑完整门禁。

## 5. D：最终分层重验（同一最终源码快照）

分层执行器：`.tmp-tests/int2e-closeout/run_validation.py`（逐层记录 command/cwd/exit_code/elapsed/source_before/source_after；源码快照=git ls-files(cached+others) 相关子树逐文件 SHA-256 的复合哈希；每层独立临时 SQLite×13 与 Chroma 目录）。层间顺序空载执行，无并行互抢。

| 层 | 命令要点 | cwd | 数量 | 退出码 | 耗时 | 源码漂移 |
| --- | --- | --- | --- | --- | --- | --- |
| L1 HTTP/审核/Dispatch/交付 | pytest apps/agent 10 文件 | 仓库根 | 66 passed | 0 | 339.62s | 无 |
| L2 Runtime/规划/门禁内核 | pytest agentOS 18 文件 | apps/agentOS | 303 passed | 0 | 399.67s | 无 |
| L3 Java 组合 | mvn -Dtest=9 类 test（surefire 53/0/0/0） | apps/backend | 53 passed | 0 | 58.59s | 无 |
| L4a 前端核心 | vitest 11 spec（maxWorkers=2） | apps/frontend | 155 passed（11 文件） | 0 | 119.33s | 无 |
| L4b Web 构建 | npm run build:web（vue-tsc+vite） | apps/frontend | — | 0 | 50.56s | 无 |
| L4c Desktop 构建 | npm run build:desktop（vue-tsc+vite） | apps/frontend | — | 0 | 26.14s | 无 |
| L5 正式冻结门禁 | python scripts/freeze_gate.py | 仓库根 | 收集 498 节点，约 375 项已过即到墙钟 | 1（INCOMPLETE_TIMEOUT） | 300.79s | 门禁自检零漂移 |
| L6 真实浏览器 E2E | 见 §5.1 | — | — | — | — | — |

最终源码复合哈希（L1 时点）：`3966c364162440a1ed3c2d58b9a7c205da7b7144b1ec30d23ca2b4ccc8a8e9d8`（L2–L5 各层 source_before/after 见 `.tmp-tests/int2e-closeout/*.result.json`，均须一致）。

### 5.1 L6 真实浏览器人工审核与最终交付（真实 DeepSeek Provider）

隔离栈 `codex-int2e-closeout-20261026`（compose 隔离命名卷、一次性凭据、`AGENTOS_LLM_PROVIDER=deepseek` + `deepseek-v4-flash`、C2 权威与 Dispatch 全开、legacy 意图关闭；容器内 ai-service 四个改动源文件与工作区逐字节一致，前端 dev 源码直出同 md5）。浏览器入口 127.0.0.1:19089，证据截图两幅（WAITING_REVIEW 审核面板、final.md 交付终态）。

全链路实录（账号 closeout_e2e 正常 IAM 注册+登录）：

1. 创建任务：Execution Control 选「人工审核」（界面实时显示「每个执行步骤完成后暂停，等待人工审核；最终交付须经批准。」，Launch Preview=Human Review）；Objective 为纯 Markdown 生成任务，**不含任何审核措辞**（审核义务只能来自配置）。
2. 真实 DeepSeek 规划并正式接受：PLANNING_ACCEPTED，两步计划（明确任务目标与约束 → 撰写并生成 Markdown 文档），ACG 2 节点 1 边。
3. 显式生命周期：准备任务图（MATERIALIZED_INACTIVE）→ 激活并保持暂停（ACTIVATED_PAUSED）→ 准备执行交接 → 申请执行许可（ISSUED）→ 执行任务（执行命令 ACCEPTED）。
4. 步骤 1 完成 → Run **waiting_review**，正式审核面板显示当前步骤、正式接口处理说明、通过/驳回与审核说明；`review_required` 可见于运行详情。批准（附说明）后恢复运行。
5. 步骤 2（交付物生成）完成 → 再次 **waiting_review**。批准前正式 API `GET /agentos/v2/runs/run_c00e10ec92bd/artifacts` 返回 `{"items":[],"total":0}`，UI Result=Final deliverable missing、OUTPUT=尚无已证明的最终产物——**密封交付物存在但不公开**。
6. 批准步骤 2 → Run completed。artifacts `total=1`（`manifest_59eed46657d84003a0ac8b722c9b4201`，sealed，checksum `8bacc5…404e5`，3280B，6 片段，artifactType=run_deliverable，artifactKey=final，semanticTaskKey=T2）；下载端点 200 `text/markdown`、Content-Length 3280 与 manifest 一致，正文即《三颗假想行星》（埃里昂/索弥尔/维洛珀）。UI OUTPUT 出现 `final.md`。

结论：human_in_loop 从配置选择到审核屏障、批准前交付不可见、批准后 canonical final 公开，全链路在真实 IAM + 真实 Provider + 正式 Runtime 下成立；auto 不受影响的合同由 L1 HTTP 回归覆盖。真实 Provider 复验缺口：无（本轮即真实 DeepSeek）。

前序真实浏览器记录（本轮保留为证据）：正常 IAM 登录通过；首条任务被真实 DeepSeek 规划为当前 C2 不支持的控制图，在接受前被 `CONTROL_BARRIER_BLOCKED` 拒绝、未进入执行（fail-closed 行为正确，计入模型非确定性证据，非缺陷）。

### 5.2 未覆盖的生产边界

真实多租户、服务端会话撤销线上演练、Provider 线上故障切换、完整灾备、原生 Windows 宿主服务、大 Artifact 容量（SpooledTemporaryFile 磁盘路径）、SSE 跨纪元持久回放、生产规模并发与容量。真实 DeepSeek 复验情况见 §5.1。

## 6. Git 与交付

远程格局（本轮入场实测）：GitHub（remote `mirror`）master=`cfe67a1e`（任务参考基线，三笔前序提交未在其上）；Gitee（remote `origin`）master=`6192be1a`（前序轮次已推，非本轮动作）。两远程均为本地 HEAD 祖先，本轮提交后理论上均可快进——但因最终裁决 BLOCKED，**本轮不推送任何远程、不部署、不改生产配置或开关、不动 Gitee**。

本轮按职责新增本地提交（在 `6192be1a` 之上）：

- `fix(agentos-c2)`：人工审核策略接线与交付公开边界（agentOS 策略/编译/接受/运行时 + agent API 合同与读取边界 + 前端说明 + HTTP/内核回归）。
- `fix(backend-gateway)`：Java SSE 计时测试改可控虚拟时钟（生产路径不变，test-scope reactor-test）。
- `fix(freeze-gate)`：时长历史 last/max 双记录与预算预检改最近完整观测剖面（含新模块 SOURCE_TEST_RULES 映射与完整性回归）。
- `docs(agentos-c2)`：本报告与 RC checklist 更新。

不重新整理无关代码；用户并行文件未触碰。历史门禁耗时缓存未清空（legacy max 全保留）。

## 7. 裁决

| 裁决项 | 结论 | 依据 |
| --- | --- | --- |
| 功能闭环（创建→规划→许可→Dispatch→审核→canonical final） | **通过** | §1、§5 L1/L2、§5.1 真实浏览器+真实 DeepSeek 全链路 |
| 架构与重构冻结（无遗留 P0/P1，正式门禁完整通过） | **未通过**（P0/P1=0；正式门禁 INCOMPLETE_TIMEOUT；不能仅由节点数量证明预算必然不可满足，§4） | §5 L5 |
| 生产就绪 | 未验收（§5.2 边界），不因功能闭环通过而宣称 READY | §5.2 |
| 允许 V1（内核）最终冻结 | 否——门禁未完整通过；V1 内核功能基线可作候选记录，正式冻结待门禁完整通过及独立复验 | §4、§5 L5 |
| 允许进入独立部署验收 | 暂不允许完整入场；审核与 Java 修复受限通过，功能面可先做只读预演，完整验收以正式门禁通过为前提 | §4、§5 |
| 推送 GitHub | 否（BLOCKED 分支规则：只保留本地已核验提交；不动 Gitee、不强推、不部署） | §6 |

历史阻断与当前状态：P1 human_in_loop 未形成正式审核要求——已修复并全链路验证（§1、§5.1）；P2 Java 组合计时失败——53/0/0/0（§3、§5 L3）；P2 冻结门禁仍未通过；原 last 估算器存在完整剖面缺口，后续定向修复见 INT-2E-ESTIMATOR-FIX，不据此改判正式门禁。

剩余 P2/P3：

- P2：正式冻结门禁未完整通过；当前环境超时证据不等于结构性不可满足的证明，后续另作性能诊断或合同裁决。
- P2：下载装配 `SpooledTemporaryFile` 1MB 阈值后磁盘路径未做容量/延迟验收（保留既有定性）。
- P2：真实多租户、服务端会话撤销演练、Provider 线上故障切换、完整灾备、原生 Windows 宿主（生产就绪边界）。
- P3：真实 Provider 规划非确定性（首条任务被规划为不支持的控制图并正确 fail-closed；可改进规划引导，非缺陷）。
- P3：SSE 瞬态流无跨纪元持久回放（V1 固有限制，保留）。
- 估算语义修正：超时不得更新完整剖面。下次仅当已有匹配的有效完整剖面且估计超出剩余预算时才在预检阻断；不存在匹配剖面则显式 UNKNOWN，不保证超时后必然阻断。

最终裁决：**BLOCKED**
