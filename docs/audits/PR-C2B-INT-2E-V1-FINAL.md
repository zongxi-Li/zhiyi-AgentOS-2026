# INT-2E V1 最终集成验收记录

日期：2026-10-25 至 2026-10-26。最终裁决：**REJECT / BLOCKED**。本记录是源码自审、定向测试及隔离环境实测记录，等待独立复验；不构成生产部署或正式发布许可。

## 1. 三层裁决与 Git 边界

| 层次 | 裁决 | 依据 |
| --- | --- | --- |
| 功能完成 | BLOCKED | 正常 IAM、真实 Provider、正式 Dispatch、Native 执行、真实 SSE、canonical final 已跑通；用户选择人工审核尚未绑定正式审核策略，完整“执行→审核→交付”未完成 |
| 重构验收 | BLOCKED | 未新增 Authority / Scheduler / 恢复引擎；交付完整性漏洞已限定修复，但人工审核接线 P1 未解决；最终冻结门禁受既定耗时预算阻断，Java 组合测试另有计时失败 |
| 生产就绪 | 未通过 | 真实租户、服务端会话撤销、Provider 线上故障、完整灾备与原生 Windows 服务验收等尚未完成 |

入场 HEAD / GitHub master：`cfe67a1e69711abf00deede0d53ed14dbfaa7928`，工作区、暂存区、未跟踪文件为空。冻结记录提交：`8b717fcff79566381ded092d193d362b4429049d`。最终源码提交及本报告提交见本文末尾的交付记录。2026-10-26 收束时再次 `git ls-remote https://github.com/zongxi-Li/zhiyi-AgentOS-2026.git refs/heads/master`，仍为入场 SHA；该提交是本地 HEAD 的祖先。未合并、未强推、未操作 Gitee。

因最终验收阻断且正式冻结门禁未通过，本轮仅本地固化可独立验证的限定修复和证据，**不推送候选版本**。未部署，未修改受控 compose、生产配置、生产开关或真实业务数据库；没有恢复用户此前删除的文档。

## 2. A：受限冻结

独立冻结记录：[PR-C2B-INT-2E-FREEZE.md](PR-C2B-INT-2E-FREEZE.md)。INT-2C / INT-2D 按 **ACCEPT WITH LIMITATIONS** 归档。已核验 Native Dispatch 认领检查及 Workbench 显式控制链；继承的 133 / 165 / 109、59 / 150 / 34 项证据、构建与浏览器记录均有原报告来源。入场独立审查没有重新运行全部历史测试，历史 SELF-TESTED 不等于生产验收。本次新增实测与继承证据分开判断。

## 3. B：真实跨栈装配与身份边界

实测环境为 Windows Docker Desktop 的 Linux 容器，专用项目 `codex-int2e-20261025`，浏览器入口 `127.0.0.1:18089`。PostgreSQL / Redis / Java / Python / Vue 五个服务使用新命名卷。Java 镜像 JDK 17，宿主 Maven 测试 JDK 21；Python 宿主定向回归为 3.14。原有 `kinlin-win-p1-001` 的配置和数据未作修改。

隔离配置生成在被忽略的 `.tmp-tests/int2e/compose.isolated.json`，没有提交 compose。仅隔离实例开启正式 C2 / Dispatch、关闭 Legacy Mission Intent，单个 uvicorn worker、无 reload。业务凭据来自该应用已配置的 DeepSeek Provider，未使用其他环境中的无关 API Key；内部服务、数据库、JWT 等使用本轮生成的隔离凭据。首次生成的资源加密密钥格式错误导致隔离启动失败，修正为有效 Fernet 格式后重建；这不是生产源码修复。所有凭据值未进入本报告或提交。

| 链路 | 当前真实接线及本次证据 |
| --- | --- |
| 浏览器→IAM | 正常注册、密码登录；Workbench DOM 创建两条 Mission，没有 HTTP 预创建任务或注入测试身份 |
| Spring Security→Java Gateway | JWT 认证上下文由 `JwtAuthenticationFilter` 建立；`TrustedUserContextForwarder` 构造内部转发身份，忽略客户端伪造 owner/role 头 |
| Java→Python | 内部服务认证中间件与 owner 校验；跨用户 Run / SSE 读取拒绝，伪造主体字段 422 |
| Planning→图→许可 | 原规划接受流程、Materialization / Activation Authority、Handoff / Permit Authority；Activation 暂停，Permit 不启动执行 |
| Dispatch→Coordinator | 既有 `POST /agentos/v2/missions/{mission_id}/runs/{run_id}/execution/dispatches`，持久命令及原 operationId 回执；原 `submit_permitted()` 管理 Task |
| Native | 原 Run lock / OS fence 下 `_claim_acg_execution()` 最终检查 Dispatch 与 Permit，原 Native Scheduler / 节点执行 / Checkpoint / 审计 |
| 读取 | `GET /agentos/v2/runs/{run_id}`、`.../events`、Run-scoped Artifact 与 Workspace 投影；浏览器经 Java `/api` 前缀访问 |

真实 IAM 负向探测脚本退出 0：匿名 Run 401；匿名伪造内部身份头 401；另一正常登录用户 Run 404；该用户伪造 owner/role 头仍 404；跨用户 SSE 404；含 `principal` 的伪造 Dispatch 请求 422；正确签名但已过期的隔离 JWT 401；篡改 JWT 401；owner Run 200。负向探测没有创建 Dispatch 或执行节点。过期 JWT 仅使用新生成的隔离签名密钥构造反例。

限制：正常 JWT 只有 userId / username / role，`JwtAuthenticationFilter` 建立的 tenantId 为 null，Python 使用 unscoped 语义；**未证明真实多租户隔离**。普通登出为客户端移除 Token，未证明服务端即时撤销已签发 Token。不能把伪造租户头被忽略称为跨租户验收通过。

## 4. 真实 Provider 与执行证据

任务一由浏览器创建：`mission_4f67d9316eda` / `run_de16d16abfbc`，非敏感“三步书桌整理清单”，关闭 Web search。逐项点击规划接受、物化、激活、Handoff、Permit，再单独点击执行。

Permit ISSUED 后、Dispatch 前：节点执行 / commit 数量均为 0，所有步骤 pending，completedStepIds 为空，executionAuthorized=false、dispatchEligible=true、dispatchCommand=null。显式执行后产生持久命令 `dispatch_50af31a036c52f164f4ed40fac29a330fda9a301`，两节点完成。未直接调用 Runtime 执行入口，未伪造 principal、Permit 或节点收据。

实际 Provider 为 **DeepSeek**，配置模型 `deepseek-v4-flash`，执行审计模型别名 `deepseek-flash`、modelVersion `1.0.0`；适配器是当前源码的 `adapters.openai_runtime.OpenAICompatibleRuntime`，经注册模型和正式传输链调用。不是确定性 Agent 的 Provider E2E。

| 节点 | 持久审计 / commit | 实际调用计量 |
| --- | --- | --- |
| native_general_agent | committed、auditOutcome=allow；audit `decision:audit:run_de16d16abfbc:native_general_agent` | 12,288 ms；prompt 1,600，completion 1,819，total 3,419；reasoning 824；toolCallCount=0 |
| native_general_agent_2 | committed、auditOutcome=allow；audit `decision:audit:run_de16d16abfbc:native_general_agent_2` | 29,009 ms；prompt 2,623，completion 5,329，total 7,952；reasoning 4,270；toolCallCount=0 |

两次业务节点调用共 11,371 tokens，**不包含规划调用**，不推算账单。两条 commit key 为 `commit:run_de16d16abfbc:{nodeId}:0:generation:agen_f6015cd4d328f8c7fb8d1a1aa9bd3fc3`，可关联同一 Run、节点、attempt、generation 与审计。只读抽取计量和引用，不归档敏感提示词。

真实 Provider 成功路径已验证。**没有对真实供应商注入 429、超时或断网**，其错误映射、重试副作用和线上恢复未验收；本地预算测试与确定性故障恢复测试不得替代它们。当前任务无外部工具副作用，不能外推任意非幂等远端操作 exactly-once。

## 5. C：真实 SSE、最终交付与恢复

第二条任务 `mission_dc67b5d3e699` / `run_3b6752cfc836` 也是浏览器完整创建和显式 Dispatch。以正常登录 Bearer 身份观察 Java→Python 正式 SSE，HTTP 200，共 **4,348** 个正确 runId 事件，sequence 1..4348 单调递增：node.started 3、model.started 3、model.activity 163、model.first_token 3、model.output.delta 4169、model.completed 3、node.completed 3、run.completed 1。三个节点真实完成；这不是测试桥 SSE 503 或仅靠轮询完成的证据。

原事件 Broker 为瞬态流，不提供持久 Last-Event-ID 回放。前端新增限定修复：正常 EOF 也重新连接；断开时清除定时器；401/403 停止自动重连；接受终态快照 sequence=0；新连接重置瞬态流序号，连接内仍去重和拒绝乱序。所有重连只观察 GET，不触发 Dispatch。轮询仍以正式 Run 持久状态为准。真实审核、取消、失败 SSE，以及完整断档补偿未验收；本轮不新增持久事件系统。

正式 final 来自现有终端生成 / canonical final identity / sealed ContentManifest，不从 supporting_artifact 提升：

| 字段 | 任务一实测值 |
| --- | --- |
| Artifact | `artifact_1eff485ff387`，artifactKey=final，artifactType=run_deliverable |
| Manifest | `manifest_1a99516a5dd641cfa4e59299ca81ce19`，sealed=true |
| 内容 | 4,122 bytes；SHA-256 `86d286f26f3a83a31993758ba05a0b50d0a79d55f8de85f56844be2719beb26c` |
| UI | Workbench 左侧 final.md，Result 显示 1 final / 0 supporting；ArtifactEditor 可读，点击下载；浏览器 WebCrypto 下载摘要一致 |
| 稳定性 | 页面刷新、页面关闭重开、新浏览器上下文密码重登录、Python 服务重建后，同一 Manifest / Dispatch / 完成状态；没有重新发出执行命令 |
| 拒绝 | 将任务一 Manifest 放在任务二 Run URL 下返回 404；跨 owner 读取 404；不泄漏摘要 |

确定性生产 Runtime + 临时 SQLite 回归另外验证：单个 canonical final、节点来源 step:C / final_synthesis、Mission / Run 引用、sealed / SHA / 长度、Workspace 引用、服务重构后无节点重执行。它与上面的真实 Provider 证据分开。现有 final 缺失展示回归保留，未增加 supporting 自动兜底。LLM 输出含额外说明性文本，未声称业务语义精确性已全面验收。

### P1 交付完整性反例与限定修复

原下载接口把 `stream_assembly()` 直接交给 StreamingResponse，Store 在末尾校验聚合摘要。将已 sealed final 首片内容损坏，真实 ASGI 响应反例为 **200 且损坏标记已返回**；发生在末尾的生成器异常无法撤回已暴露字节。红态退出 1。

在 API 层先将原 Store assembly 写入 1 MiB 内存阈值的 SpooledTemporaryFile，完整校验后再发送 HTTP 200，额外比较 byteLength；失败统一 503。读取片段页也比较每片 SHA / 长度与 sealed 状态。没有改变 Store / Schema / final Authority。永久回归包含 fragment、checksum、length、unsealed 四类损坏；unsealed 沿用既有隐藏资源的 404。

隔离真实 final 另做一次故障注入：仅修改专用数据库第一片，Java 下载返回 **502**（上游 Python 503），损坏标记未暴露；finally 还原原片，随后正常 IAM 下载 200，4,122 bytes 与上述 SHA 相同。未接触真实业务数据库。

限制：下载在返回首字节前需要完整校验，较大内容使用临时磁盘，增加 I/O 与 TTFB；未做容量/性能验收。片段页只校验所读片段，不声称抵御能同时重写所有内容和校验元数据的任意数据库写入者。

### 未解决的 P1：人工审核意图没有形成正式策略

第二条真实任务在创建页选择 **human_in_loop**，目标明确要求人工审核。Run payload 持久 reviewMode=human_in_loop，但三个步骤 reviewRequired=false，最终 status=completed；正常登录 `GET .../runs/run_3b6752cfc836/reviews` 为 200、total=0，没有 WAITING_REVIEW。

源码定位：`agentos_v2.py` 接收/保存 reviewMode，`workflow_runtime.py` 将 review_mode 写入 Run；同步正式图时按 `node.review_required` 设置 `step.requires_review`。`components/executor/node_runner.py` 使用 `step.requires_review or persisted_decision.outcome == "review"` 正确建立审核屏障。Native Agent 输出未把自然语言“高风险”变成可信风险策略，review_mode 没有在正式规划/接受流程绑定为 typed 审核要求。

这是**产品人工审核选择与正式策略的接线缺口**，不是“已有 reviewRequired=true 被 Native 绕过”的证据。自由文本也不能直接成为执行权限。安全修复需要明确 human_in_loop 在正式规划接受时的语义、审核范围和可信策略来源；本轮不通过前端假暂停、修改既有已接受图、或运行时强制改标志来制造通过。发现后停止扩大完整审核链及发布候选验收，记录 BLOCKED，未修改冻结核心合同。

现有永久回归仍覆盖 Permit-only 零执行、稳定 key / ACK 丢失、不同 key 并发单拥有者、取消、终态、Checkpoint、审核重放阻断、证据不足恢复阻断、Provider/LocalRuntime 故障、Dispatch disabled / Legacy。它们是定向合约证据，不能替代此次未完成的真实人工审核全流程。

## 6. D：升级、恢复与资源关闭

只在新卷中显式执行 C2 `upgrade_databases(..., initialize_empty=True)`，再安装 Dispatch Schema version 1，退出 0。新增空库回归证明反序安装失败且不增加事实，正确顺序 READY；关闭连接后从 SQLite backup 恢复旧版本逻辑内容一致，旧 Schema 的 Dispatch 构造 fail-closed。

真实任务完成后先停止隔离 AI，再将 AgentOS 数据目录的 **9 个 SQLite 文件**逐文件 backup / restore 到独立目录；逻辑 SQL dump 摘要全部一致，恢复副本 C2=READY、Dispatch=1；重复显式升级不改变逻辑事实，演练退出 0。另以不存在 Schema 的独立 `/tmp` 路径启动真实装配，进程退出 **1**，错误为必须显式升级 Mission semantic schema。检测脚本识别预期拒绝而退出 0，两种退出码不混用。

此演练为单实例、关闭写入后的逐文件离线恢复，**不承诺跨库原子性**。未覆盖 PostgreSQL IAM 灾备或所有其他路径的资源数据库，不构成整站生产回滚验收。重启完成任务没有节点补跑；未知副作用阻断主要复用永久故障注入测试，未在真实供应商上制造不确定远端副作用。

本轮另修复 Coordinator shutdown：Task 若在首次进入协程前被取消，其 finally 不会运行，可能遗留 `_tasks` 句柄。红态确定性复现退出 1；shutdown gather 后只移除本轮已完成 Task，永久回归通过；未放宽 submit 或执行权限。

结束时 `docker compose -f .tmp-tests/int2e/compose.isolated.json down` 退出 0，五个专用容器及网络已移除，18089 无监听；原有五个容器仍健康。10 个专用生成/复制凭据文件在核验绝对路径及非 reparse point 后逐文件删除。测试数据卷保留供独立排查，不提交数据库。没有清除历史门禁耗时缓存，未停止原运行栈。浏览器专用页已关闭。

## 7. 分层测试、真实退出码与源码快照

命令 cwd：R=`C:\Users\LZX\Desktop\kinlin_ai`；P=`R\apps\agentOS`；J=`R\apps\backend`；F=`R\apps\frontend`。以下是实际执行，不含全量 pytest。

| 层 | collected / passed / failed / skipped | 退出码与结果 |
| --- | --- | --- |
| 最终 HTTP / Auth / Artifact / Coordinator | 59 / 59 / 0 / 0 | 0；408.10 s（进程包装 413.98 s） |
| 最终 Runtime / Authority / Recovery / Schema | 160 / 160 / 0 / 0 | 0；534.14 s（包装 542.41 s） |
| Vue / API / 状态 / 审批 / Artifact | 155 / 155 / 0 / 0，11 文件 | 0；91.33 s |
| Java 组合，执行两次 | 每次 53 / 52 / 1 / 0 | 1；`AiSseGatewayServiceTest.idleTimeoutResetsOnEventsAndIsDistinctFromMaximumDuration:99` |
| Java 不含 SSE 计时类 | 46 / 46 / 0 / 0 | 0；与上行是不同命令 |
| Java SSE 类单独执行 | 7 / 7 / 0 / 0 | 0；不能覆盖组合失败 |
| Web 类型检查 + 生产构建 | 非测试计数 | 0；Vite 35.34 s |
| Desktop 类型检查 + 生产构建 | 非测试计数 | 0；Vite 29.40 s；未声称原生安装包启动验收 |
| 冻结门禁，修复前源码 | 302 / 302 / 0 / 0 | 0，273.989 s，300 s 原预算 |
| 冻结门禁，最终源码 | collection_exit_code=0；pytest 未启动、计数不适用 | 1；BLOCKED_KNOWN_DURATION_OVER_BUDGET，10.058 s |

最终 HTTP 命令（R）：

```powershell
python -m pytest apps/agent/tests/test_agentos_c2_dispatch_admission.py apps/agent/tests/test_agentos_c2_dispatch_http.py apps/agent/tests/test_agentos_c2_dispatch_projection.py apps/agent/tests/test_agentos_c2_final_delivery.py apps/agent/tests/test_execution_coordinator.py apps/agent/tests/test_internal_service_auth.py apps/agent/tests/test_agentos_v2_artifact_api.py apps/agent/tests/test_provider_timeout_budget.py apps/agent/tests/test_provider_output_budget.py -q --disable-warnings --maxfail=1
```

最终核心命令（P）：

```powershell
python -m pytest tests/components/planner/test_graph_handoff.py tests/components/planner/test_execution_permit.py tests/components/planner/test_permit_recovery.py tests/components/planner/test_permit_recovery_final_audit.py tests/runtime/test_fault_recovery.py tests/runtime/test_dispatch_admission.py tests/runtime/v2/test_artifact_identity.py tests/components/auditor/test_artifact_acceptance.py tests/storage/test_c2_release_rehearsal.py tests/storage/test_c2_schema_upgrade.py tests/storage/test_runtime_assembly_failure_cleanup.py tests/test_runtime_live_events.py -q --disable-warnings --maxfail=1
```

前端命令（F）：

```powershell
npm exec vitest -- run src/components/workspace/FormalExecutionControls.spec.ts src/components/workspace/RunProgressEditor.spec.ts src/views/MissionWorkspaceView.spec.ts src/views/CreateMissionView.spec.ts src/workbench/runtime/observation.spec.ts src/workbench/runtime/runtimeEvents.spec.ts src/components/agentos/WorkflowReviewPanel.spec.ts src/composables/useWorkflowReview.spec.ts src/components/workspace/ArtifactEditor.spec.ts src/services/api/agentos.spec.ts src/services/api/agentos/api/c2.spec.ts --maxWorkers=2 --minWorkers=1
npm run build:web
npm run build:desktop
```

Java 命令（J）：

```powershell
mvn -q -Dtest=SecurityRouteMatrixTest,AuthControllerTest,JwtUtilTest,TrustedUserContextForwarderTest,PythonServiceAuthenticationTest,AiSseGatewayServiceTest,AgentOsMissionControllerTest,AgentOsRunControllerTest,QueryProjectionArchitectureTest test
mvn -q -Dtest=AiSseGatewayServiceTest test
mvn -q -Dtest=SecurityRouteMatrixTest,AuthControllerTest,JwtUtilTest,TrustedUserContextForwarderTest,PythonServiceAuthenticationTest,AgentOsMissionControllerTest,AgentOsRunControllerTest,QueryProjectionArchitectureTest test
```

Java 计时反例使用已有 25 ms 心跳、80 ms idle / 70 ms maximum，组合运行时预期 maximum 的断言失败；本轮没有调整超时、降低断言或修改 Java 生产实现。归为待隔离计时/负载问题 P2，组合门禁保留失败。

冻结命令（R）两次均为 `python scripts/freeze_gate.py`，未改参数、基线或缓存。首次报告 `tmp/freeze_gate/20261026T000134Z.json`，302 个 nodeids、pytest_exit_code=0；最终报告 `20261026T002645Z.json`，历史估计 315.82 s > 剩余 289.943 s，pytest_command=null / pytest_counts=null。首次通过不能代表最终源码通过；直接定向回归不能替代正式冻结门禁。

局部红绿证据保留：交付损坏红态 exit=1 → 四类损坏与既有 Artifact 共 5 passed / exit=0（84.56 s）；取消未启动 Task 红态 exit=1 → Coordinator / 取消 / shutdown 7 passed / exit=0（31.49 s）；SSE EOF 与 sequence=0 红态 exit=1 → runtimeEvents 11 passed / exit=0（6.18 s）。一次修复前 HTTP 运行 26 passed / 1 failed（取消句柄），中间 56 passed 的运行伴随源码变化，不作为最终快照。原 Python 小层 37 passed / exit=0 仅为补充，不叠加冒充独立覆盖数量。

最终 HTTP、核心测试前后 tracked 源码集合摘要均相等：`74269d51a9efe7063dff839a8c8216cb14a98ddb13f50207095297f61ba53fa0`。计算集合为 `git ls-files apps/agent apps/agentOS apps/backend/src apps/frontend/src scripts` 的各文件工作区 SHA-256，按路径排序 JSON 后再 SHA-256；新增尚未跟踪测试另列下表。修复前门禁运行的该集合摘要为 `5cd846565ca19303db344fa6bf26a86b851662039c182567a99f54ddabc1d6dc`。门禁自己的 457 文件摘要为另一个集合，不与此混用。

下表“前”为入场 Git blob 字节，“后”为测试结束工作区字节；Windows 换行归一化可能使 blob 与工作区摘要不同，不能据此声称文件都改过。

| 文件 | 入场 SHA-256 | 测试后 SHA-256 |
| --- | --- | --- |
| apps/agent/app/api/agentos_v2.py | 1ef46eb4cdceaf2f0df6ece5e748fc65fd41b765d544e7fa914989b8400c514e | b373afcec52b0479d5214cbd43c84adfd4a35cb268e0ddcc49c4f74e9d3e2f9c |
| apps/agent/app/execution/coordinator.py | 68eff00cdc1c8c3d44794330aae0ac94b5a0bac1f4d252ce1e592fe34426822c | a4d3cbef8b7bbf7613fb91e2d2be8e581e11c5724a6671e9e42845612b6cffec |
| apps/agent/tests/test_execution_coordinator.py | c040c8657e0403671c8b4b069d79cce52fae6ad3cd1113c20f5d90196b900597 | b6767dfe41a7336482f948b1a7ea9c2e57ee2847da4762384e530d987a89b33f |
| apps/frontend/src/workbench/runtime/runtimeEvents.ts | 600907241b58b8634701cf71dec14dec09baff17c6c0a255679f4aa17b6155a4 | 3287d14a1ccb414c43839055c90b5c9fa332fbc956a4ddb4e5f61351f42e7606 |
| apps/frontend/src/workbench/runtime/runtimeEvents.spec.ts | b6f0310f39a8b62e1c4bf319488ddd3608dfb3fc423ee32f2161cc2ffb7e3694 | d571001611bd2fd906865e33d49bc95e05491664fe88ed93a5ca12f4f80776de |
| apps/agent/tests/test_agentos_c2_final_delivery.py | NEW | 24a561f23999ee8f48a5f461bf4cb98fea19fec95e8d907190cff73732aaffaa |
| apps/agentOS/tests/storage/test_c2_release_rehearsal.py | NEW | 06412481fcbb6942823f7ea5e5ceff4cd38d3492e82eaf61124e41e40e74d479 |

本机原始日志与命令结果保留在忽略目录 `.tmp-tests/int2e/`：http/core 的 `.log` 与 `.result.json`、frontend-final、build-web/desktop、java-final / java-without-timing / java-sse-isolated、artifact-integrity-red / artifact-final-green、coordinator-red/green、sse-eof-red / sse-zero-red、live-backup / schema-refusal、auth-result、live-ledger。未把 tmp、数据库、机器缓存或凭据提交进 Git。报告保留关键结果，机器日志不保证随克隆分发。

`git diff --check` 退出 0。构建产物已检查已知测试身份桥、测试服务 Token、隔离账号密码标记，未命中；这不是完整凭据扫描或软件供应链验收。正常响应的授权/Artifact 负向回归未泄漏内部签名；未声称全量生产日志均已审计。

## 8. 问题等级、后续条件与限制

| 等级 | 状态 / 后续条件 |
| --- | --- |
| P0 | 本次已检查范围未发现；不等同完整安全审计 |
| P1 | 人工审核选择→正式策略接线缺口未解决，阻断完整 V1；需可信策略语义及真实审核浏览器反例转绿 |
| P1 | final 损坏内容先返回后校验已限定修复，四类永久回归及真实隔离注入通过，待独立验收 |
| P2 | 最终冻结门禁时间预算阻断；Java 组合计时失败；真实 tenant / 服务端撤销、Provider 故障、SSE 审核/取消/失败与断档、完整灾备、原生 Windows 服务及容量尚未验收。作为生产入场条件处理，未验证不记通过 |
| P2 | Coordinator 首次调度前取消的句柄残留、SSE EOF / 序号零 / 新连接游标问题已限定修复，回归通过 |
| P3 | 大 Artifact 预校验耗时/磁盘容量、LLM 语义质量与交互细节需独立评估，不在此扩展 |

保留单实例锁、跨数据库非原子、瞬态事件、远端非幂等副作用不确定时阻断等合同。没有分布式正确性、任意外部操作 exactly-once 或生产扩容证明。阶段 C/D 按实际证据有限收束，没有因其他层通过而跳过人工审核阻断。

V1 最终冻结：**不允许**。完整独立部署验收入场：**尚不允许**；可以先独立复验已完成限定修复和上述阻断证据。需解决人工审核策略，重新完成正式冻结及组合门禁，补齐身份/Provider/恢复/运行环境必需证据后再裁决。不自动进入后续阶段，不开放生产开关。

## 9. 交付记录

源码限定修复本地提交：`113129ecc05c158347cba7b51dd51f40e2b54ee6`，`fix(agentos-c2): 收束交付校验与取消事件恢复边界`，7 文件、234 增加 / 5 删除。冻结与源码分组提交，报告另作提交；标题遵守英文类型/模块及中文描述。源码提交后再次核验入场远程 SHA 是 HEAD 祖先（退出 0），差异仅含本轮 7 个源码/测试文件和冻结文档。最终 SHA、远程复核及差异范围在最终交付回复和 Git 历史中给出；本报告不嵌入自身提交 SHA，以免循环改变内容摘要。简短候选清单：[PR-C2B-INT-2E-V1-RC-CHECKLIST.md](PR-C2B-INT-2E-V1-RC-CHECKLIST.md)。
