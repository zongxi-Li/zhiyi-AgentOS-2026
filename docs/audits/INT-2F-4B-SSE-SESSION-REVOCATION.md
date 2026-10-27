# INT-2F-4B：SSE 会话撤销安全闭环实施报告

日期：2026-10-27（Asia/Shanghai）。本轮连续完成：INT-2F-1 固化核实、INT-2F-4A 独立复核与提交、INT-2F-4B SSE 撤销改造与提交，并推送 GitHub master。不部署、不运行正式冻结门禁、不修改真实业务数据库。

## 一、INT-2F-1 固化状态

**已固化，无需重复提交**。入场核实：HEAD 历史 `cf8a2b4c493c261dbf2979f98c4d391fb9e1c285` 即 `fix(coordinator): 清理首次运行前取消的任务句柄`，`git show --stat` 确认严格包含且仅含三个文件（coordinator.py +13、test_agentos_c2_dispatch_http.py +44、test_execution_coordinator.py +54）；三个文件当前工作区零未提交修改。GitHub 实时 master 与入场本地 HEAD（071a8d1f）一致。

## 二、INT-2F-4A 独立复核结论

**通过，无 P1 安全缺陷**。重新走查生产 diff 与真实源码（不采信自测报告）：

1. JWT 必须含有效 sid 且服务端按持久会话认证：`JwtAuthenticationFilter` 要求 username/userId/sid 三非空 + 验签 + `LoginSessionService.isSessionActive` 主库点查，缺一不设认证。
2. 已撤销/过期/不存在会话不能访问受保护接口：isSessionActive 四条件（存在、归属匹配、未撤销、未到期）。
3. 会话库不可用 fail-closed：filter 捕 DataAccessException → 503 `auth_state_unavailable` 且不进 filterChain；verify 同为 503。
4. logout 仅撤销当前认证主体的会话：sid 取自 SecurityContext（生产代码唯一 `setAuthentication` 点在 filter，grep 复核）；无请求体可指定他人 sid；兼容 principal 分支构造的上下文 sid=null 被 401 拒绝。
5. 登出失败前端不误报：`serverRevoked` 区分，网络失败 warning 提示"撤销未确认"。
6. Flyway V11 与 V1-V10 兼容：`PostgresMigrationIntegrationTest`（含空库全集重放 + validate）4/4。
7. 无绕过路径：测试切片 mock 仅存在于测试上下文；`AuthenticatedUserContext` 兼容构造器 sid=null 无法通过 logout/受保护链路。

定向复跑（隔离 POM，真实退出码 0）：会话合同 6/6 + 持久状态 4/4 + DB 故障 3/3 + PG 集成 2/2 + PG 迁移 4/4 + AuthController 18/18 + JwtUtil 5/5 + 路由矩阵 2/2 + Observability 2/2 = **46/46**；前端 auth/request/App/router = **40/40**。

**INT-2F-4A 提交：`ee16607f`（feat(iam): 持久登录会话与服务端登出撤销），父节点 071a8d1f，28 文件 +1275/−71，仅含 4A 实现与测试及其实施报告，未混入 SSE 改造与任何并行会话内容。**

## 三、SSE 实际调用链与改造前后差异

真实链（本轮逐层核对源码）：浏览器 fetch 流 → `AgentOsEventController` GET `/api/agentos/v2/runs/{runId}/events` / POST `…/copilot/messages/stream` → `AiSseGatewayService.openGet/openPost`（filter 已认证的 context 经 `TrustedUserContextForwarder` 重建身份头 + `PythonServiceAuthentication` 内部令牌）→ WebClient →（真实 HTTP）→ Python `/runs/{id}/events`。

| 行为 | 改造前（INT-2F-2 审计确认） | 改造后 |
| --- | --- | --- |
| 建连认证 | filter 验 JWT（4A 起含会话） | 不变；另拒绝无 sid 上下文（401 AI_STREAM_SESSION_REQUIRED） |
| 连接期会话状态 | 只受 idle(240s)/max(1800s) 时长约束，撤销后旧流继续交付 | 每流 SessionRecheckGate：周期（默认 3s，含建连首查）经 SessionActivityProbe 复核同一 iam_login_sessions 权威；撤销/过期/查询失败/租期耗尽 → 停止交付、尽力发送 `auth.invalidated`（仅 code）终止事件、取消上游订阅 |
| 空闲流 | 无会话复核 | 同一周期任务驱动，不依赖业务事件 |
| 撤销后重连 | —（4A 起 filter 401） | 不变，已撤销会话不能恢复流（真实 401 断言） |
| 前端主动登出 | 只清本地凭证，旧流继续跑到自然结束 | `kinlin:auth-logout` 广播中止全部运行时事件流 + 清重连定时器；收到 `auth.invalidated` 立即断流不重连 |

时间与资源合同（INT-2F-3 §7，任务书数值）：复核周期 P=3s（`ai.sse.session-recheck-period-ms`）；单次查询订阅级超时 Q=1s（Reactor timeout）+ 语句级 1s（JPA `jakarta.persistence.query.timeout`，findBySid）；有效观测租期 L=5s（从查询开始时刻 t0 起算，迟到结果在订阅取消后无处投递、无权延长租期）。取消上界 = P+Q = 4s ≤ 5s。单流最多一个在途查询（CAS 护栏）；查询在专用有界调度器（`sse-session-recheck`，8 线程/64 队列）执行，不占 Reactor 事件线程。复核失败 fail-closed（立即终止），未关闭 TLS、未忽略数据库异常。连接池获取等待（Hikari 全局 30s）不是合同依赖：订阅级 1s 超时先行终止交付；极端池饱和时阻塞线程的释放滞后为已知边界（见 §六）。

## 四、新增与修改文件

**INT-2F-4A 提交 `ee16607f`（28 文件）**：生产 9（LoginSession/LoginSessionRepository/LoginSessionService/V11 迁移/JwtUtil/JwtAuthenticationFilter/AuthController/SecurityConfig/AuthenticatedUserContext）+ 前端 3（auth.ts/requestAuth.ts/AuthenticatedAppShell.vue）+ 测试 15 + 4A 报告。

**INT-2F-4B 提交 `5e80df0c`（16 文件，+1170/−17）**：
- 生产 6：`gateway/SessionRecheckGate.java`（新）、`gateway/AiSseGatewayService.java`（每流套门+终止事件+计量）、`security/SessionActivityProbe.java`（新，SSE 复核与 HTTP 认证共用权威的窄接口，维持 J1.2 分层——gateway 不得 import service）、`service/LoginSessionService.java`（实现探针）、`repository/LoginSessionRepository.java`（findBySid + 语句级 1s 超时）、`application.yml`（sse 三键）
- 测试 8：SessionRecheckGateTest（新 6）、AiSseGatewaySessionRevocationTest（新 5）、AiSseGatewayServiceTest（更新 7）、SseSessionRevocationEndToEndTest（新 4）、SseSessionRevocationPostgresTest（新 1）、SessionStateUnavailableTest（更新 3）、前端 runtimeEvents.spec/auth.spec（更新）
- 前端 2：`services/api/auth.ts`（登出广播）、`workbench/runtime/runtimeEvents.ts`（广播监听断流 + auth.invalidated 帧停流不重连）

Python 侧零改动：内部服务认证、Coordinator、Dispatch、Permit、Runtime 合同不变。

## 五、测试结果（真实退出码）

| 层 | 命令（cwd apps/backend，隔离 POM `.int2f4a-validation.xml`/独立 build 目录，历史 target 报告零触碰） | 结果 | 退出码 |
| --- | --- | --- | --- |
| 4A 复核定向 | `-Dtest=SessionRevocationHttpContractTest,…,PostgresMigrationIntegrationTest,…`（9 类） | 46/46 | 0 |
| Gate 单元 | `-Dtest=SessionRecheckGateTest` | 6/6 | 0 |
| 网关级（loopback 真实 HTTP + 真实时钟短参数） | `-Dtest=AiSseGatewaySessionRevocationTest` | 5/5 | 0 |
| 端到端真实网络（RANDOM_PORT 真实过滤链 + loopback 事件源，生产参数 3s/1s/5s） | `-Dtest=SseSessionRevocationEndToEndTest` | 4/4；**撤销→auth.invalidated 实测 2569ms**（合同 ≤5000） | 0 |
| PostgreSQL 持久权威（pg-it Testcontainers + loopback） | `-Dtest=SseSessionRevocationPostgresTest` | 1/1；**实测 2746ms**；撤销后重连 401 | 0 |
| 架构守卫 | `-Dtest=ArchitectureGuardTest` | 30/30 | 0 |
| 后端全量 | `mvn -o test -f .int2f4a-validation.xml` | **567/567**（01:31） | 0 |
| 前端全量（cwd apps/frontend） | `npx vitest run` | **702/702**（104 文件，111.87s） | 0 |

覆盖对照任务书必测清单：有效会话正常交付 ✓；活跃流撤销停发 ✓（终止事件后零 delta 断言）；空闲流撤销停止 ✓；复核查询失败/超时停止交付 ✓；撤销后重连拒绝 ✓（真实 401）；跨用户会话隔离 ✓（Alice 登出 Bob 流继续交付断言）；前端登出中止 SSE 与自动重连 ✓（fetch abort + 重连定时器清零断言）；多次取消/断连/正常关闭不泄漏 ✓（active gauge 回落断言 + 单流 timer/sink 幂等关闭）。

过程性失败 2 项均已定位修复（非环境噪音、未清缓存改预算）：① ArchitectureGuard 抓到 gateway→service 分层违规 → SessionActivityProbe 接口落 security 包；② 网关级"重连拒绝"用例语义错误（建连认证属 filter，初租期放行 filter 已认证观测是设计语义）→ 删除并由端到端真实 401 用例覆盖。另：pg-it profile 缺 `ai.internal.token`（此前无出站调用未暴露）致 PG SSE 测试 503，测试类注入 test 同款非生产令牌修复。

## 六、Git 固化与推送

- INT-2F-4A：`ee16607f`（父 071a8d1f=入场 GitHub HEAD），28 文件。
- INT-2F-4B：`5e80df0c`（父 ee16607f），16 文件。
- 本报告单独提交（`git log -1 --format=%H -- docs/audits/INT-2F-4B-SSE-SESSION-REVOCATION.md` 定位），随后推送。
- 推送：显式 URL `https://github.com/zongxi-Li/zhiyi-AgentOS-2026.git HEAD:refs/heads/master`（不使用 mirror 双 push URL，Gitee 不动），推送前实时核对远端 HEAD 为 071a8d1f 祖先链、不强推。推送后 GitHub 实时 master 见 §八。
- 保护核验：`scripts/freeze_gate.py`（fb834c0a…）、`test_freeze_gate_integrity.py`（06d23d14…）、`tmp/freeze_gate/test_durations.json`（c02e3af5…）SHA-256 与入场一致；drawio 删除保持原状；docs/audits 既有未跟踪文档全部保留；未提交、未暂存任何并行会话内容。

## 七、尚未解决的生产部署限制

1. **未部署**：运行中的 backend 容器仍是旧镜像，需三文件重建后才具备会话撤销能力；重建后所有存量 JWT（无 sid）立即失效，全部用户需重新登录（强切换语义，不支持无感回滚）。
2. **取消时延边界**：3s/1s/5s 合同针对可调度的存活网关进程的交付准入/取消动作；撤销时已进入 Servlet/OS/TCP 缓冲区的数据不可收回；进程 stop-the-world 期间不承诺物理断连时限（INT-2F-3 §7.2 边界保留）。
3. **连接池饱和边界**：复核查询的 1s 合同由订阅级超时保证，语句级 1s 由 PG/H2 支持；Hikari 连接获取等待（全局 30s）未单独收紧——池耗尽时流的取消时延仍达标（1s 超时先行），但占用线程的释放可能滞后至获取超时，属已知边界而非合同缺口。
4. 未实现（与 4A 遗留一致）：过期会话清理任务、改密/删用户联动撤销全部会话、多设备会话管理端点、审计字段、多实例部署验证（当前单实例合同；多实例需共主库且禁旧版实例）。
5. `auth.invalidated` 为尽力发送（HTTP 200 已发出后无法改状态码），可丢失，不作为撤销成功依据；成功撤销的权威事实只在 iam_login_sessions。

## 八、GitHub 远端 HEAD

推送目标为 `ee16607f`（4A）+ `5e80df0c`（4B）+ 本报告提交三笔。本报告不含自身提交 SHA（避免循环引用）；推送后以实时 `git ls-remote` 核对远端 master 与本地 HEAD 一致、无分叉，核实结果记录于最终交付消息。

## 九、下一阶段工作

1. 部署窗口：三文件重建 backend（Flyway V11 自动迁移）+ 前端发布，通知全员重新登录；重建后浏览器端到端验收（登录→建流→登出→流终止→重连 401）。
2. 会话运营配套：过期会话批量清理（expires_at 后保留期建议 30 天，待运营确认）；改密/删用户联动撤销。
3. 多设备会话管理（GET /auth/sessions + DELETE /auth/sessions/{sid}，含跨用户 404 隐藏语义）。
4. 多实例/负载均衡下的会话合同评审（共主库、禁止新旧认证实例混跑）。
5. V1 冻结单独管理，不作为本轮阻断；门禁 498 节点 vs 300s 结构性冲突仍待用户裁决（10-26 遗留）。
