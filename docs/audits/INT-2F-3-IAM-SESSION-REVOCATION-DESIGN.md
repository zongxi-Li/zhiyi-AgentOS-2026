# INT-2F-3：IAM Session Revocation Contract & Design

日期：2026-10-27（Asia/Shanghai）。阶段结论：**DESIGN ONLY，等待下一阶段实现授权**。V1 仍未正式冻结。本报告只新增设计文档，没有实现撤销、修改认证行为、运行测试、提交、推送或部署。

标记：**CONFIRMED** 为本轮实际代码/Git 只读核验；**PROPOSED** 为推荐合同，尚未生效；**NOT_IMPLEMENTED** 为当前缺失能力；**NOT_VERIFIED** 为没有本轮运行验收的能力。不得将设计数值或前序测试计数视作本轮通过证据。

## 1. 入场与证据保护（CONFIRMED）

- HEAD/master：`071a8d1f8abe823dfbbeea933280a556cf7bf6c5`。直接父节点 `cf8a2b4c493c261dbf2979f98c4d391fb9e1c285`，其父为 `53eb030023dd2f2c631a222df3786dfd18fc1fa5`。
- `git show --stat` 确认 INT-2F-1 提交仅 Coordinator、Coordinator 测试、Dispatch HTTP 测试三文件；INT-2F-2 提交仅前序审计报告。前序报告描述与本轮读取源码一致；其 4/52/14 项证据是历史运行记录，本轮未重跑。
- `git ls-remote <显式URL> refs/heads/master`：GitHub 为 `071a8d1f8abe823dfbbeea933280a556cf7bf6c5`，Gitee 为 `53eb030023dd2f2c631a222df3786dfd18fc1fa5`。本地 master 跟踪 origin/master，显示 ahead 2，不应把 Gitee 跟踪引用当作 GitHub 实时状态。
- `mirror` fetch URL 为 GitHub，push URL 同时包含 GitHub/Gitee；origin 指向 Gitee。本轮没有 fetch、修改引用或 push。
- 暂存区为空。已有 tracked 修改：`scripts/freeze_gate.py`、`apps/agentOS/tests/storage/test_freeze_gate_integrity.py`；另有 `docs/架构设计/架构图/知弈AgentOS_ACG总体架构.drawio` 删除。删除来源本轮无法解释，**保留原状**，不归属本设计，也不恢复或暂存。
- 7 份既有未跟踪审查文档保留：三份 ESTIMATOR-FIX-REVIEW-REMEDIATION（原版/-2/-3）、REMEDIATION-3-FINAL-INDEPENDENT-REVIEW、REMEDIATION-5-FORMAL-INDEPENDENT-REVIEW、REMEDIATION-6-PERFORMANCE-REVIEW、INT-2F-1-COORDINATOR-CANCEL-CLEANUP。

只读命令包括 `git status --porcelain=v1 -uall`、`git branch -vv`、`git log -4 --oneline`、`git diff --stat`、`git diff --cached --stat`、`git remote -v`、两端显式 `git ls-remote`，以及下述源文件的 Get-Content/rg。未读取环境密钥或真实业务数据库；配置审计只确认配置机制，不核验运行中数据库内容。

入场 SHA-256（原始文件字节）：

| 对象 | SHA-256 |
| --- | --- |
| freeze_gate.py（既有修改） | `fb834c0ad42dcfa9c51e1a1dc0ad879f13d4de1493988ab85e6523cd01e96484` |
| test_freeze_gate_integrity.py（既有修改） | `06d23d14368d2a35a197e9ff886142b8cb0d4167f29b525adb168a244f9a0f83` |
| INT-2F-2 审计报告 | `b83d6970518b5a73cbe86c7e13c0ad7a962099b45ed92f1781910a80dbb53f5f` |
| tmp/freeze_gate/test_durations.json | `c02e3af5018b675ef6bb68fb60c0370aa1e21bd5017225afa33d0cb5a5970519` |

保护快照算法：对 `git ls-files` 与 `git ls-files --others --exclude-standard` 的路径去重排序，逐文件原始字节 SHA-256（不存在记 null），以 UTF-8 `json.dumps(records, sort_keys=True, ensure_ascii=False)` 再摘要。入场 2211 项，集合摘要 `28f86e484d8d982fa71a7b8a46f6fa32ed596d77babe1483d2be5b6e26de173c`。完工核验排除本报告后应相同。另对 `tmp/freeze_gate` 全部 90 个现存文件，使用排序路径→摘要字典和默认 `json.dumps(..., sort_keys=True)` 得到 `6bf5edb94af5d85c2725c8e791ea2f2b0bfb3bfefc7fec479208531710008614`，包含旧失败报告、manifest、缓存及原有锁文件，不删除任何文件。

## 2. 当前真实调用链（CONFIRMED）

下列路径相对仓库根目录；Java 包根为 `apps/backend/src/main/java/com/kinlin/ai/`。

| 边界 | 实际代码与行为 | 当前缺口 |
| --- | --- | --- |
| 登录/注册 | `controller/AuthController.java` login/register → `service/UserService.java` → `repository/UserRepository.java`/`entity/User.java` → `util/JwtUtil.java` | 登录不创建服务端会话；注册也直接签发 JWT，不能只改 login 漏掉 register |
| 用户持久化 | JPA users，UUID 主键、唯一 username/email、password_hash、审计时间；UserService 创建/改密/删除有事务 | 没有 session、撤销字段或主体撤销权威；updatedAt 不是安全版本 |
| JWT | JwtUtil 用本地签名密钥签发 userId/username/role=USER/sub/iat/exp；配置默认 exp 24 小时，typed JwtProperties 验证配置 | 没有 sid/jti，没有找到 refresh Token、刷新路由或刷新流程；重复登录生成独立 Token，但当前无法稳定标识登录会话 |
| 新请求 | `filter/JwtAuthenticationFilter.java` 解析签名及 exp，创建 `security/AuthenticatedUserContext.java`；`config/SecurityConfig.java` STATELESS | JWT 校验不查 users/session；tenantId=null；/auth/** 整体跳过过滤且 permitAll |
| 身份转发 | `gateway/TrustedUserContextForwarder.java` 从可信 context 重建用户/角色/租户头；PythonServiceAuthentication 加内部服务 Token | 不转发浏览器 JWT；当前 context 无 sid/Token 到期信息 |
| Python 入站 | `apps/agent/app/security/internal_auth.py` 校验内部密钥、唯一必要身份头，建立 TrustedUserContext | 信任 Java 服务身份；不校验浏览器 JWT，不持有 IAM 会话表 |
| HTTP 控制 | AgentOsMissionController → 原 AgentOsClient → Python middleware → Mission/Run owner/write → Coordinator/Dispatch/Permit/Native | 撤销不能重写执行许可或已经接受的 Dispatch |
| SSE 建连 | `controller/AgentOsEventController.java` GET events/POST copilot stream → `gateway/AiSseGatewayService.java` openGet/openPost 捕获可信 context，WebClient 转发 | 只在建立时认证；无连接期会话复核 |
| SSE Python | `apps/agent/app/api/agentos_v2.py::stream_runtime_events` 调用 load_run/_require_access，再订阅 `apps/agentOS/src/runtime/live_events.py::RuntimeEventBroker` | broker 是 Run 分发器，不是授权权威；不知 sid |
| SSE 结束 | Java Flux idle timeout/maximum duration/下游取消，instrument 计量；Python subscribe 的 finally 移除 queue，最后订阅移除时清理 Run 项；终态/overflow 结束 body | Java 取消到 Python 清理的实际时间本轮未运行验证；不能从 finally 推断所有网络故障都即时释放 |
| 浏览器 | `apps/frontend/src/services/api/auth.ts` logout 仅清 localStorage；verifyToken 有 30 秒正向 UI 缓存 | 没有服务端登出；UI 缓存不能参与后端授权 |

Java 默认 SSE idle 240000ms、maximum 1800000ms，ASYNC continuation 对已授权响应放行。JWT 过期、流最大时长、客户端断开是不同事实，均不等于主动撤销。INT-2F-2 已观察到过期后原流仍有事件，本轮仅确认对应代码没有新增撤销机制。

IAM 数据库机制：正式 application/prod/compose 使用 PostgreSQL/JPA、Hibernate `ddl-auto=validate`、Flyway `db/migration`；当前迁移 V1 至 V10。dev/test 使用 H2 create-drop/Flyway disabled，不能以其通过替代 PostgreSQL 真迁移验收。Redis 配置存在，不构成会话权威。数据库配置与 Python Runtime SQLite/Identity/Checkpoint 是不同边界，不承诺跨库原子性。

没有发现可用的管理员会话授权：JWT 正常签发 USER；roles 表为业务角色/Persona，不能据其名称授予 IAM 管理员。`AuthenticatedUser.currentContext()` 还有 UUID/String 兼容 principal 分支；未来会话敏感操作必须要求过滤器产生的完整 session context，不能让这些兼容分支制造有效 sid。

## 3. 粒度决策（PROPOSED）

| 方案 | 权威/成本 | 旧 Token、权限与多实例影响 | 决策 |
| --- | --- | --- | --- |
| A 单 Token jti | 每个 Token 持久 allowlist 或撤销 denylist；有刷新后需分别维护 | 旧 JWT 无 jti；denylist 缺项语义及清理需严格定义；撤销整个登录需枚举 | 暂不引入。当前没有只撤销一个刷新后 Token 的需求 |
| B 登录会话 sid | 每次登录一行；每新请求一次主库点查，已建流周期点查 | sid 必须被签名且与 userId/到期匹配；无 sid 迁移要明确；所有实例查同一主库 | **默认采用**，在现有 Java IAM 中增量扩展 |
| C 主体全部会话 | 同一权威表批量撤销，并与该主体新登录串行化 | 普通用户仅自己；管理员需独立授权；不能只做无锁批量 UPDATE 而漏掉并发新登录 | 独立操作，下一阶段最小实现不开放管理入口 |

当前一登录一 Token，没有刷新。设计仍让 sid 代表登录会话：未来一个 sid 可有多个轮换 Token，但不得延长 session.expires_at；刷新、轮换和 refresh 凭证本轮不设计为已具备功能。重复登录创建不同随机 sid，A 登出不影响同用户 B。默认 logout 仅撤销当前 sid，不退出其他设备。

普通用户可撤销自己的任一 sid；他人 sid 不暴露存在性，返回 404。管理员撤销他人/全部会话必须有可信权限来源、审计和单独授权设计；当前**NOT_IMPLEMENTED**，不得只信请求体 role 或现有 persona。

## 4. 唯一持久权威与数据模型（PROPOSED）

在现有 IAM PostgreSQL/Flyway 内增加 `iam_login_sessions`，现有 UserService/认证服务和 Spring Data JPA 扩展负责读写。它是现有无状态 IAM 的持久化增量，禁止再建立 Python Session Store、Redis 正式状态、进程字典黑名单或另一个 IAM 服务。

| 字段 | 合同 |
| --- | --- |
| sid UUID PK | 服务端安全随机 UUID v4，数据库唯一约束；冲突时重试生成，不接受客户端指定；不是持有即可登录的秘密 |
| user_id UUID NOT NULL FK users | 绑定稳定用户 ID；校验用户仍存在。物理删除用户先定义会话审计保留流程，不随意 cascade 丢失撤销审计 |
| created_at / expires_at TIMESTAMPTZ | UTC、服务端可信时间；expires_at > created_at；签名 JWT exp 不得晚于此时间；序列化按 JWT 秒精度统一 |
| revoked_at nullable TIMESTAMPTZ | null=尚未主动撤销；非 null 永不恢复为 null。EXPIRED 由到期派生，避免第二份状态相互冲突 |
| revoked_by_user_id nullable UUID | 当前可信操作主体 ID 快照；不接受请求体 principal；不必 FK 到可能被删除的操作者 |
| revocation_reason / trace_id | 服务端枚举 SELF_LOGOUT/SELF_REVOKE/未来管理原因及经校验 trace；禁止任意敏感上下文、JWT、密码、密钥入库/响应/日志 |
| version BIGINT | JPA 乐观版本或等价条件更新保护；不能据 version 生成执行许可 |

约束至少包括 revoked_at 与撤销审计字段一致性、合法 reason、时间次序、user_id FK。索引 sid PK、user_id（必要时 user_id/revoked_at）、expires_at 用于清理。客户端不能写会话状态、到期时间或 actor。不储存原始 JWT，不增加独立正式状态表；首次撤销事实与必要审计字段同事务持久化，普通日志只是辅助证据。

**登录事务**：密码校验成功后，在现有 IAM 服务事务创建 sid 并生成绑定 JWT；仅在事务提交成功后返回 Token。签名失败则回滚会话创建。register 当前也发 Token，必须统一走同一会话签发路径；注册可将 user/session 同事务提交，不允许签发无 session Token。表缺失或版本不兼容，启动 fail-closed，禁止自动回退旧无状态认证。

**撤销线性化点**：主库事务提交首次 `revoked_at` 更新。用持有当前可信 userId 的条件更新/行锁复核目标所有者，记录首次操作者与时间；并发更新失败后重新读取同一行，已撤销则保留原事实。遇到死锁、连接或提交结果未知不返回成功，给 503；相同目标重试不会复活会话。不得在提交前发送成功或以日志记录代替提交。

**新请求读取**：签名/exp/必需 claims 校验成功后，按 sid 从主库以新短事务 READ COMMITTED 查询，不走只读副本、跨请求 Hibernate 一级缓存或正向缓存。验证 sid/userId 关联、用户存在、expires_at、revoked_at、JWT exp 不超上限，才创建 authenticated context。未知 sid/损坏关联拒绝 401；数据库不可查询返回 503 且不进入 Controller/上游，不把基础设施失败伪装成“有效”。会话检查不得放宽 Python owner/tenant/write。

HTTP 保证是**撤销提交先于本次认证读取**时拒绝；已经完成认证且与撤销并发的在途请求可能继续，撤销不取消已接受的 Dispatch、不撤回 Permit、不自动取消 Run。不承诺 Java IAM 与 Python 执行事实跨库线性化。需要取消业务执行时仍用原受控 cancel。

无必要不加缓存。尤其不做“有效 30 秒”的服务端正向缓存；前端 verify 的 UI 缓存不改变上述规则。多实例以后也必须读同一主库，不能凭单实例通知充当权威。

保留策略建议：会话直到 expires_at 后至少 30 天再批量清理（待运营/合规确认，此处不是法规结论）。未过期记录不得清理；撤销不延长可认证时间。删除后未知 sid 永远拒绝，不是默认为有效；旧 Token 即使因时钟误差到达也不能复活。清理按主库时间及安全余量、有界批次、可审计，审计长期留存需求另行决定，不能删除后宣称仍有完整历史。

主体全部撤销若未来实现：登录创建 sid 与 revoke-all 均锁同一 users 行，统一 user→session 锁序，提交批量撤销时覆盖该串行序中先前所有会话，之后的新登录可生效。不能声称一次 revoke-all 永久禁止未来登录；封禁用户是另一合同。下一阶段不增加未经授权的管理员 endpoint。

## 5. JWT 迁移（PROPOSED）

| 策略 | 安全与用户影响 | 回滚限制 |
| --- | --- | --- |
| 强切换，拒绝缺 sid 的旧 JWT | 推荐。切换后全部重新登录；所有有效凭证都能映射持久会话，不“自动补建”旧会话 | 回滚到旧仅验签版本会再次接受已撤销 Token，属于安全降级；必须停止入口并重新裁决，不能无感滚回 |
| 明确截止时间兼容旧 JWT | 过渡窗口内旧 Token 仍只能依赖 exp，无法满足完整撤销；需分别标记 legacy-unrevocable 并禁止冒充保证 | 容易把安全语义混用，必须硬截止且所有实例一致；不推荐当前需求 |

推荐签发新增 `sid` 和明确会话协议版本 claim（如 `sessionVersion=1`）；保留当前 userId/sub/role/iat/exp，版本只由服务端签发。未知版本、缺 sid、sid 格式非法或没有对应行均 401 `SESSION_IDENTITY_REQUIRED`/`INVALID_SESSION`，客户端重新登录。旧 JWT 即使验签成功也不能隐式注册到表中。当前无刷新机制，不设计后台静默续签迁移。

发布顺序：先备份并在隔离 PostgreSQL 演练显式 Flyway 新版本（当前 V10，实施时重新核对再分配版本，不修改旧 migration）；验证 Hibernate validate；维护窗口关闭旧连接/旧实例；部署所有入口使用会话检查；重新登录。禁止新旧认证实例混合服务并宣称撤销一致。Schema 增量可保留，但身份行为回滚不等于可安全回退源码。改密、删用户以后如何撤销全部会话需明确实施，当前方法不能被误称为已有能力。

## 6. HTTP 合同（PROPOSED，全部撤销接口 NOT_IMPLEMENTED）

下一阶段复用 AuthController/原认证路径，先收紧 `JwtAuthenticationFilter` 与 `SecurityConfig`：只精确公开 login/register/verify 等必要端点，不能继续 `/auth/**` 全跳过、全 permitAll。verify 虽可保持查询式公开路由，也必须调用同一会话验证服务；不能让只验签的旧实现返回 valid=true。

| API | 输入与授权 | 成功/失败及持久含义 |
| --- | --- | --- |
| POST /auth/login、/auth/register（现有） | 原密码认证/注册验证；sid/时长由服务端生成 | 200 原响应兼容并返回新 JWT；只有 session 提交后才返回。无效密码 401；持久失败 503，不发凭证 |
| GET /auth/verify（现有） | Bearer，复用会话验证 | 保持 200 `{valid:false}` 的既有查询合同可行；有效才 true。DB 不可用必须 503，不缓存为有效、不返回异常内部信息 |
| POST /auth/logout（增量） | 无身份请求体，只取当前已认证 context.sid | 首次撤销提交后 204；当前会话已撤销后的重放认证为 401，**不为响应幂等而允许 revoked JWT 进入认证 context** |
| DELETE /auth/sessions/{sid}（增量） | 有效会话仅可操作属于自己的目标，查询/更新时再核对所有者 | 当前有效会话 A 撤销自己 B：首次及重复已撤销目标均 204；他人/不存在均 404；参数格式错 400。A 撤销 A 后重放 401 |
| 主体全部会话/管理员撤销 | 独立管理合同 | 本轮设计不开放 URL；普通用户不得借请求体 userId/role 升权，不能把未实现接口 404 当授权通过 |

幂等定义是持久状态单向、首次审计不被重写，不承诺失效凭证仍能得到相同 HTTP 204。无须给一次单向条件更新新增 operationId Store。ACK 丢失时当前 logout 重试可能 401，表示无法继续认证；不能仅凭通用 401 推断那次撤销已经提交。要精确确认，可重新登录后用新有效会话撤销旧 sid，重复返回 204。客户端本地保留旧 sid 只作目标标识，不能作为凭证。

错误体采用结构化 code/traceId：401 为凭证无效/到期/会话无效，403 留给已认证但无操作权限（跨用户目标统一 404 隐藏）；503 `AUTH_STATE_UNAVAILABLE` 表示无法判定，禁止继续业务。错误不得包含 SQL、库连接信息、密钥或原 Token。客户端展示区分过期、撤销与认证服务不可用可使用受限 code；详细判因记录可信审计，不向匿名枚举 sid。

前端 logout 必须先尝试服务端撤销，再清本地 token/verify 缓存并中止本页所有 SSE、轮询和重连。网络失败仍可本地退出，但提示“本机已退出，服务端撤销未确认”，不能显示“所有设备已撤销”。不保留原 Token 在 localStorage 作重试队列，不把失败当成成功；其他泄漏的凭证仍可能有效直到完成撤销或到期。

## 7. 已建 SSE 的失效合同（PROPOSED）

### 7.1 方案比较与选择

| 机制 | 优点 | 单独使用的不足 |
| --- | --- | --- |
| 每事件查主库 | 每次交付有新的权威观测 | 高频事件数据库成本高；空闲连接永远不查；JPA 不能阻塞 Reactor event loop |
| 周期复核 | 空闲也能发现；已有 Flux 生命周期即可承载 | 必须限制检查时效，不能查询挂住还无限转发 |
| 注册连接、提交后主动关流 | 单实例低延迟 | 重启、漏通知、多实例仍需权威复核；新增注册机制并非必要前提 |

第一阶段采用 **原 AiSseGatewayService 内周期主库复核 + 每次交付前本地短期有效性检查**。每条流只持有临时检查结果/取消信号，不创建持久连接状态机，不建立独立 SSE 管理器，不引入广播。点查服务与新 HTTP 共用同一 session 权威。暂不做主动注册关闭；以后即使增加通知也只是加速，不能替代查询。

### 7.2 明确时限和并发语义

建议固定首版验收参数：复核间隔 P≤2 秒（从上次采样开始计时，不是慢查询结束再等 2 秒）；会话查询总超时 Q≤1 秒；有效观测租期 L=3 秒；关闭/取消处理余量 C≤2 秒。**网关停止接纳新受保护事件最迟为撤销提交后 3 秒；取消本条 upstream 订阅的目标上界为 5 秒。** 均为待实现/待验收合同，不是当前实测保证。

一次观测只可从查询开始的 monotonic 时间 t0 授予至 t0+3 秒，不能从返回时间重新计时；只用主库新事务读已提交事实。若 t0 后发生撤销，该观测最多留存至 t0+3。查询返回过迟/乱序结果不能更新租期；每条流只允许一个在途查询，结束后的回调不能复活已终止流。每事件（含 Python 已缓存/排队数据及终态快照）**在交给下游之前**必须检查未终止、租期未过及 JWT/session 未到期，不能预先检查后无限排队。避免向下游过量预取；终止时丢弃尚未交付内容。

签名 JWT exp 和 session.expires_at 是独立到期上限；有效租期取三者最早值。到期不等待下一轮查询才停发。观测到 revoked/unknown/关联错误/查询失败时立即关闭交付门并取消，不能继续使用此前仍未到期的正向观测。查询未返回时最迟在旧租期到期停止转发。空闲流也运行定时器，不能依赖下一个业务事件或 idle timeout 才查。

上述上界针对**可调度的存活网关进程**的下游交付准入/取消动作；不承诺公网浏览器最后收到一个字节的时间。撤销时已进入 Servlet/OS/TCP 缓冲区的数据不可收回，允许撤销并发的已准入事件最后到达。不是严格即时撤销，更不是远端按 wall clock 的零泄漏证明。进程长时间 stop-the-world、OS 调度停止或网络黑洞时，不能证明 5 秒内物理断连；进程恢复后必须先检查截止、不可继续交付旧租期数据。这些限制必须在产品安全说明中保留。

取消订阅的 5 秒目标可通过 Reactor 取消回调/上游连接关闭验证；Python broker 最终清理须另用真实 TCP/ASGI 链断开测试。若关闭传播失败，必须停止 Java 向浏览器交付并记录资源清理失败；不宣称 Python 队列已在 5 秒内必然释放。若产品要求端到端物理释放硬上界，未完成独立服务端断连保障前该要求保持 BLOCKED，不能用本地 cancel 调用次数冒充。

实现预留：JPA 查询放在有界阻塞工作池，单流在途查询≤1；独立定时器控制门和取消，不受 DB worker 阻塞影响。现有连接池等待默认 30 秒不满足 Q=1；需对这些短查询设置可测试的连接获取/语句/总等待期限和并发上限。仅 Reactor timeout 不证明底层 JDBC 被取消，迟到 worker 必须无权延长租期，压测证明不会无界堆积。若当前驱动/池无法满足，实施阶段需缩小目标并报告阻断，不能在源码未验证前承诺资源上界。

### 7.3 场景合同

| 场景 | 期望行为 |
| --- | --- |
| 新 SSE / 撤销后重连 | 普通 JWT+session 验证不通过则建连前 401，无 Python 订阅；DB 不可查询 503。订阅前还需复核初始观测时效，不能使用长时间挂起的连接准备结果 |
| 有流量、撤销已提交 | 按 L/C 边界关门/取消；在途事件按上述准入语义处理 |
| 空闲、撤销已提交 | 周期复核触发终止，不等新事件；同样 L/C 上界 |
| 已发送 SSE HTTP 200 后失效 | 无法再改 HTTP 为 401。可尽力发送不含业务数据的 `auth.invalidated`（仅 code/trace），随后结束；此通知可丢失，不作为成功撤销依据 |
| 同用户不同 sid | 只按本流 sid 复核，撤销 A 不关闭 B；不按 userId 误关全部流 |
| 不同用户/Run | 身份隔离复用原 owner/write 检查；session 有效不代表拥有任意 Run。Python broker 不新增鉴权职责 |
| DB 故障 | 新连接 503；已建流观测失败立即停发，挂起最迟租期耗尽停发，再取消。不得从副本/缓存猜测仍有效 |
| 关闭失败/重启 | 先关闭 Java 交付门，取消只幂等一次；重启没有旧连接，新建连接重新查库，已撤销不能恢复 |

必须覆盖 openGet 与 openPost，而非只保护 Run events。Java 已发响应的会话终止异常不能被现有通用 `onErrorResume` 转成业务流继续；只允许终止型无敏感错误事件。沿用现有 instrument/doFinally 计量，验证一次 decrement，无负数/残留句柄。下游关闭取消 WebClient 上游，Python body 结束后 broker.subscribe finally 清理；不取消任务执行、不发送新 Dispatch、不消费其他会话订阅。

信任边界不变：Python 仍验证内部服务身份和 owner，不复制会话表、不开浏览器 sid 查询入口。Java→Python 在途请求可能跨过撤销点；受信内部服务 Token 的持有方并不受浏览器会话撤销控制，故网络隔离和服务凭据保护仍是前提。第一阶段只声明单实例验收；未来多实例要共同主库且禁止旧版本实例，不能把单机通过外推为分布式已验收。

## 8. 持久状态、连接状态与故障语义（PROPOSED）

持久有效性为 `exists && user matches && revoked_at is null && now < expires_at`，REVOKED 和 EXPIRED 可同时为真；无状态枚举互相覆盖。用于诊断优先给 revoked 原因，再给到期，但 JWT 本身已到期可先被验签库拒绝。

| 状态/转换 | 持久事实 | 请求/连接行为 |
| --- | --- | --- |
| 不存在 → ACTIVE | 登录事务提交 session | 提交前不能使用新 JWT |
| ACTIVE → REVOKED | 首次撤销提交 revoked_at | 不允许返回 ACTIVE；新认证拒绝；旧流按第 7 节截止 |
| ACTIVE → EXPIRED（派生） | 到 expires_at，无需定时写状态 | 新认证拒绝；旧流按到期截止停发 |
| REVOKED → 到期/清理 | 保留首次撤销审计，达到保留期后可删除 | 删除后 UNKNOWN sid 仍拒绝，不能复活 |

连接临时生命周期只在原 Flux 中管理：未订阅 → 已打开 → 停止交付/取消 → 已结束。它不是第二套持久会话权威；断连不代表 session 已撤销。

| 故障切点 | 裁决与恢复 |
| --- | --- |
| 登录事务失败/签名失败 | 不返回 Token；回滚 session。register 同事务场景一并回滚用户创建 |
| session 已提交、Token 响应丢失 | 孤立有效 session 到期后清理；再次登录新 sid，不能猜测复用未收到的 Token；不保证登录 exactly-once |
| 撤销事务失败/提交结果未知 | 503、禁止报告已撤销；重试相同目标条件更新，确认实际主库状态 |
| 撤销提交、ACK 丢失 | 事实保持；当前凭证重试 401，不允许其继续控制；另一有效自有会话可重复撤销目标获 204 |
| 重复/并发撤销 | 首次事实唯一且不覆写审计，其他调用得到已撤销结果；当前调用认证与撤销竞争可能为 204 或 401，但不得恢复有效 |
| SSE close 失败 | Java 已关交付门；记录清理失败，不重新订阅或重派发；底层资源释放上界 NOT_VERIFIED |
| 进程重启 | 会话/撤销依主库，旧连接消失；不依赖进程字典；重连重查，不唤醒 Run |
| 旧 JWT 延迟到达 | 缺 sid 按强迁移拒绝；绝不现场补建会话 |
| DB 暂不可用/查询积压 | 新请求 503，既有流按租期停发；恢复后必须客户端新连接完整认证，不让旧流自动恢复 |
| 撤销与业务请求并发 | 已准入请求可完成；不承诺撤销撤回已提交执行命令，取消走原 Runtime 控制链 |

## 9. 下一阶段最小实现范围（PROPOSED）

1. 在现有 IAM 内增加一个会话实体/Repository/共享认证验证服务及一个追加 Flyway migration；提供隔离 PostgreSQL 升级/缺表失败测试，禁止触碰真实业务库。
2. login/register 统一创建会话和签名 sid；JwtUtil 增加 claims、context 增加 sid/到期；filter 精确公开路由，保护其余新接口；verify 复用同一权威。复查 UUID/String 兼容 principal 不能通过 session 操作。
3. 当前 logout 与自有 sid 撤销；事务、所有权、幂等、结构化错误。全会话/管理员撤销暂不开放，保留单独设计约束。
4. AiSseGatewayService 原 openGet/openPost 增加单条流的周期复核/交付门/取消；共用 IAM reader，不增新事件源/Store/广播。先红侧验证已建流与空闲流，再实现。
5. 前端 logout 调用服务端、清 UI verify 缓存、停止现有流和重连，准确展示未确认撤销；不改 Permit/Dispatch/Runtime 权限。

禁止顺带增加刷新体系、跨库分布式事务、Python 会话权威、全局角色管理或分布式广播。若 3/5 秒合同无法验证，提交明确反例/阻断，不能换一套未审定的宽松语义制造绿测。

## 10. 下一阶段验收矩阵（测试计划，不新增测试源码）

测试分层：真实 Spring Security+AuthController+UserService+实际 session Repository；临时独立 PostgreSQL 执行真实 Flyway 与重启；真实 Java WebClient→Python InternalServiceAuthMiddleware→Run owner→RuntimeEventBroker SSE。H2 可做快速回归，但不替代迁移、锁隔离和 PostgreSQL 验收。loopback 计数源只作特定转发/时序辅助；不是实际会话权威或跨用户授权证明。

| ID | 场景与可复现步骤 | 必须核验的证据 |
| --- | --- | --- |
| T01 | 注册/正常登录→提取签名 sid→查询隔离库 | 唯一 session、userId/iat/exp 一致；Token 仅提交后返回；重复登录不同 sid；密码失败零 session |
| T02 | 有效会话实际控制请求→logout 提交→同 Token 控制 | 前者按原权限；后者 401，Python 请求/控制事实计数不增加，不能仅看状态码 |
| T03 | 撤销后新 SSE/重连（GET 和 POST） | 401 且 Python broker 无新增订阅、上游无业务载荷 |
| T04 | 已建真实流→提交撤销→持续发布带唯一标记事件 | 主库提交时间、采样开始、交付准入/取消时刻；≤3 秒停止准入、≤5 秒发出取消；核验实际浏览器关闭及 Python 订阅最终释放，不用回调次数替代 |
| T05 | 空闲流无业务事件→撤销 | 不靠 publisher 推进，周期复核停止；实际时间集成验收与可控时钟边界单测分别记录 |
| T06 | 同用户 A/B 两次登录，各建流→撤销 A | A HTTP/SSE 失效，B 不受影响；重复登录不共用 sid |
| T07 | 用户 A/B 各自 session→A 撤销 B 或读 B Run | session API 404、数据库 B 行原样；Run owner 按既有拒绝；B 仍正常，不能用无 owner 校验的计数源冒充 |
| T08 | 同一有效 A 并发撤销自有 B，重复多次 | 多个 204、首次 revoked_at/actor 不变、状态不复活；当前 A 自撤销重放 401；ACK 丢失后另一自有会话重试 |
| T09 | 签名有效但缺 sid/版本错/sid 不存在/绑定用户错 | 强迁移均拒绝，不自动建行、不转发；不能把任意 sid 请求体当凭证 |
| T10 | 分别触发 JWT exp、session expires_at、主动撤销 | 所有边界拒绝；原因可审计且互不冒充；过期连接不等下一业务事件才停 |
| T11 | 主库断连、连接池耗尽、慢查/迟到结果 | 新 HTTP/SSE 503，旧流≤租期停发；迟到结果不能延租/复活；worker 数量有界、日志无敏感细节 |
| T12 | 撤销后关闭 Java，使用同一隔离持久库重启 | 旧 sid 新请求 401；未撤销会话按到期仍可用；不能用内存 H2 新库重建代替持久重启 |
| T13 | 下游阻塞/关闭失败、上游迟到事件、expiry 与 revoke 竞争 | 交付门关闭后零新准入，取消幂等、无跨流关闭、计量不负数；物理资源清理失败明确报告 |
| T14 | 两用户各自真实 Run/并行事件流 | 身份和内容隔离；撤销一个 session 不影响另一个用户，也不广播敏感撤销原因 |
| T15 | 登录提交失败、Token 响应丢失、撤销提交 ACK 丢失 | 故障切点真实注入；主库事实与 HTTP 结果分开检查；无假成功、无自动重发 Dispatch |
| T16 | 原 Dispatch/Permit/Review/cancel、UI refresh/logout 回归 | 撤销只影响后续认证与流；未 Dispatch 零执行，已接受命令不被认证修复重解释；客户端 logout 停重连 |
| T17 | 空库/现有 Schema 隔离副本升级、缺表、未知版本 | Flyway 真迁移+validate；不自动回退、旧数据不丢；不修改真实库/旧 migration |

所有下一阶段运行应保存独立 artifact ID、命令/cwd、真实退出码、collected/passed/failed/skipped、墙钟、源码前后摘要、隔离库标识（不含密码）及原始失败。先红后绿，强断言实际磁盘/库状态和真实 HTTP/已建流；不得把特征测试通过当撤销功能通过。本阶段没有执行上述测试或正式门禁。

## 11. 风险、待决边界与禁止宣称

- **NOT_IMPLEMENTED**：整个持久 session、撤销 API、sid 迁移、已建流复核；本报告不改变当前风险。要求可撤销会话的生产使用仍缺前提。
- **PROPOSED**：B 默认粒度、强切换、HTTP 语义、3/5 秒 SSE 合同及 30 天建议保留；它们是下一阶段实现/验收基准，不是现有 SLA。
- **NOT_VERIFIED**：主库故障时 JDBC 取消与线程池容量、真实 TCP 关闭到 Python 队列清理时限、进程调度暂停、真实多实例/租户、会话劫持处置、生产性能/灾备。下一阶段必须优先验证有界复核实现可行性。
- 多租户目前 context.tenantId=null；不能由本设计宣称租户撤销隔离已具备。管理员角色来源、主体全撤销、密码变更/删除用户联动需独立限定实现，不挪用业务 roles。
- sid 不是 CSRF 防护、客户端凭证安全或内部服务认证的替代；现有 Bearer/TLS/服务边界仍需保持，不关闭 TLS 验证、不日志记录 JWT。
- 禁止宣称即时撤销、撤销回滚已提交业务操作、跨数据库原子性、远端副作用 exactly-once、跨纪元 SSE 持久回放或 V1 已冻结。

本阶段交付仅为可实施设计。下一阶段获得明确授权后方可新增生产实体、迁移、接口或测试源码；本轮不自动进入实现。

## 12. 完工核验（CONFIRMED）

新增本报告后重算并排除本报告：原 2211 项保护集合摘要仍为 `28f86e484d8d982fa71a7b8a46f6fa32ed596d77babe1483d2be5b6e26de173c`；90 份门禁历史文件集合摘要仍为 `6bf5edb94af5d85c2725c8e791ea2f2b0bfb3bfefc7fec479208531710008614`。原有删除项仍为不存在，没有恢复；所有既有 tracked/untracked 文件及缓存、历史门禁证据无本轮变化。

`git diff --check HEAD` 真实退出码 0；`git diff --cached --quiet` 退出码 0（暂存区仍为空）；HEAD 未变。LF/CRLF 提示为既有两份门禁修改的 Git 提示，未执行换行重写。最终状态仅比入场新增本设计报告；没有新增测试源码、运行测试或正式冻结门禁，没有提交、推送或部署。设计等待独立审阅与下一阶段明确实现授权。
