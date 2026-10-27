# INT-2F-4A：最小 IAM 持久会话与 HTTP 撤销实施报告

日期：2026-10-27（Asia/Shanghai）。结论：**实现完成，自测全绿，交付独立验收**。不提交、不推送、不部署；未运行正式 V1 冻结门禁。

依据：INT-2F-2 审计（撤销 NOT_IMPLEMENTED）与 INT-2F-3 设计（PROPOSED 合同）。本轮按任务书收敛为个人开发应用级最小方案：登录会话 sid 粒度、强切换拒绝旧 JWT、单一 `iam_login_sessions` 持久权威、POST /auth/logout。设计中的多设备会话管理、管理员撤销、Refresh Token、Redis 缓存、分布式撤销通知、完整 SSE 生命周期改造均未实现（见遗留）。

## 一、实际修改

生产代码（apps/backend，包根 `com/kinlin/ai`）：

| 文件 | 修改 |
| --- | --- |
| `entity/LoginSession.java`（新增） | `iam_login_sessions` 实体：sid(PK)/userId/createdAt/expiresAt/revokedAt；EXPIRED 由到期派生不落状态 |
| `repository/LoginSessionRepository.java`（新增） | PK 查询 + `@Modifying` 条件撤销（首次写 revoked_at，重复撤销不覆写） |
| `service/LoginSessionService.java`（新增） | createSession（时长与 JWT exp 同源于 `app.jwt.expiration`，同一时刻创建）/ revokeBySid（幂等）/ isSessionActive（存在+归属匹配+未撤销+未到期；DB 异常上抛 fail-closed） |
| `db/migration/V11__create_iam_login_sessions.sql`（新增） | PG 表+user_id FK+expires_at/user_id 索引；未触碰 V1-V10 |
| `util/JwtUtil.java` | `generateToken(userId, username, sid)` 签入 `sid` claim（旧两参签名删除，强切换）；新增 `getSidFromToken` |
| `filter/JwtAuthenticationFilter.java` | 公开路径收窄为 `/auth/login`、`/auth/register`、`/auth/verify` 精确匹配；认证链增加 sid 必需 + `isSessionActive` 主库校验；DataAccessException → 503 `{"error":"auth_state_unavailable","traceId":...}` 且不进 filterChain |
| `controller/AuthController.java` | login/register 统一"创建会话→签发含 sid Token"，会话创建失败 503 绝不发 Token；新增 `POST /auth/logout`（仅撤销当前会话，须过滤器产生的含 sid 上下文）；verify 复用同一会话权威 |
| `config/SecurityConfig.java` | permitAll 从 `/auth/**` 收窄为 login/register/verify 三条精确路径 |
| `security/AuthenticatedUserContext.java` | record 增加 `sid` 字段；保留无 sid 兼容构造器（兼容分支 sid=null，过不了 logout） |

前端（apps/frontend）：

| 文件 | 修改 |
| --- | --- |
| `services/api/auth.ts` | logout 先 POST /auth/logout（8s 超时）再清本地凭证；204→"退出登录成功"；401→"登录凭证已失效，本机已退出"；网络/5xx→"本机已退出，服务端撤销未确认"；返回 `serverRevoked` 区分，绝不误报撤销成功 |
| `utils/requestAuth.ts` | `/auth/logout` 加入 caller-owned 401 白名单（主动登出不弹"登录状态已过期"） |
| `components/app/AuthenticatedAppShell.vue` | `serverRevoked=false` 时用 warning 样式提示"撤销未确认"，不用成功样式 |

Python 侧零改动：内部服务认证、Coordinator、Dispatch、Permit、Runtime、SSE 网关合同不变。

测试（新增 4 类 + 更新 10 个既有类）：新增 `SessionRevocationHttpContractTest`（6）、`SessionRevocationPersistenceTest`（4）、`SessionStateUnavailableTest`（3）、`SessionRevocationPostgresIntegrationTest`（2，隔离 Testcontainers PostgreSQL 15.17）；更新 AuthControllerTest/JwtUtilTest/SecurityRouteMatrixTest/ObservabilityExpositionTest/OperationalProjectionTest 及 5 个 mock-JwtUtil 切片/集成测试（补 LoginSessionService mock 与 sid stub）。

## 二、接口行为

- `POST /auth/login`、`POST /auth/register`：密码校验/用户创建成功 → 同步创建持久会话 → 返回含 sid 的 JWT（响应结构不变）。会话创建失败 → 503 + `登录服务暂不可用，请稍后重试`，无 token。密码错误 → 401，零会话行。
- `POST /auth/logout`（受保护）：首次撤销当前会话 → 204；原 JWT 此后任何受保护接口 401。重复退出（同 JWT）→ 401（不为幂等响应放已撤销凭证入认证）。无认证/兼容分支上下文 → 401。撤销持久化失败 → 503（不伪装成功）。
- `GET /auth/verify`（公开查询式）：有效会话 → `{valid:true,...}`；已撤销/过期/无 sid 旧 Token → `{valid:false}`；会话库不可用 → HTTP 503 `{valid:false, message:认证服务暂不可用}`。
- 任何受保护路由：JWT 验签+exp 通过后按 sid 查主库；无 sid、会话不存在/不匹配/已撤销/已过期 → 401；会话库不可查 → 503，不进入业务 Controller（测试用 mock Controller verify 零调用证明，非仅状态码）。
- 同用户多次登录 = 独立 sid 会话，登出一个不影响其他（测试覆盖）。

## 三、测试结果（全部真实退出码）

| 层 | 命令（cwd 见括号） | 结果 |
| --- | --- | --- |
| 红（实现前） | `mvn -o test -f .int2f4a-validation.xml -Dtest=SessionRevocationHttpContractTest`（apps/backend，隔离 POM/独立 build 目录） | **6/6 失败**（logout 404×5、无 sid JWT 200×1），与 INT-2F-2 审计现状一致 |
| 会话合同 | 同上（实现后） | 6/6 通过（14.65s） |
| 持久状态+业务链路 | `-Dtest=SessionRevocationPersistenceTest` | 4/4 通过（revoked_at 真实落库断言 + mock UserController 零调用） |
| DB 异常 fail-closed | `-Dtest=SessionStateUnavailableTest` | 3/3 通过（认证 503+零业务调用/登录 503 无 token/撤销 503 且会话保持有效） |
| 隔离 PostgreSQL | `-Dtest=SessionRevocationPostgresIntegrationTest`（Testcontainers postgres:15.17-alpine，真实 Flyway V11 + Hibernate validate） | 2/2 通过（22.06s；表/列存在、双会话行、revoked_at 落库、撤销后 401/未撤销仍有效） |
| 后端全量 | `mvn -o test -f .int2f4a-validation.xml` | **551/551 通过**（BUILD SUCCESS，01:25） |
| 前端全量 | `npx vitest run`（apps/frontend） | **699/699 通过**（104 文件，92.83s；含 auth.spec 12、request.spec 8） |
| Python 证据性回归 | `python -m pytest apps/agent/tests/test_internal_service_auth.py -q`；`test_agentos_v2_api.py` 两个 SSE 用例 | 6 passed + 2 passed（本轮零 Python 改动） |

测试断言了真实持久状态（JPA/JdbcTemplate 直查 `iam_login_sessions`）与是否进入受保护业务链路（mock Controller verify），不是仅按 HTTP 状态码判定。既有 `target/surefire-reports` 历史报告未触碰（隔离 build 目录 `target-int2f4a`，测试后已清，证据归档于 `.tmp-tests/int2f-4a-iam-session/`：隔离 POM、关键 surefire 报告、红绿记录 `red-green-record.md`）。

## 四、遗留问题与已知边界

1. **已建立 SSE 流不受本轮撤销影响**（任务书明确暂不实现）。撤销只保证新请求/新 SSE 建连被拒；已建流仍受既有 idle(240s)/maximum(1800s) 时长约束，撤销后可能继续交付事件到自然结束——INT-2F-2 已实测该边界。下一阶段按 INT-2F-3 §7 做 AiSseGatewayService 周期复核+交付门（3/5 秒合同）。
2. **强切换影响**：部署本版后所有存量 JWT（无 sid）立即失效，全部用户需重新登录。回滚到旧版本会重新接受（本版已撤销的）无 sid Token，属安全降级，不支持无感回滚。
3. 撤销与在途请求并发：撤销提交先于认证读取的请求必被拒；已完成认证的并发在途请求可完成；不撤回已接受的 Dispatch/Permit（与 INT-2F-3 §4 合同一致）。
4. 未实现：过期会话清理任务（保留策略待运营确认）、改密/删用户联动撤销全部会话、多设备会话列表/管理端点（如设计的 DELETE /auth/sessions/{sid}）、审计字段（revoked_by/reason/trace_id/乐观锁 version）。sid 冲突重试未实现（UUID v4 随机 PK，碰撞概率可忽略；表中 sid 由服务端生成，不接受客户端指定）。
5. verify 的 503 响应体使用既有 Token 投影（`valid:false`+message），HTTP 503 状态码是"无法判定"信号；filter 的 503 用 `error:"auth_state_unavailable"` 体，两处形态不同但均不泄露内部细节。
6. 运行期容器尚未部署本版（不提交/不部署）；生产 `ddl-auto=validate` 下部署时 Flyway V11 自动迁移，V11 已在隔离 PG 验证可重放（`migrationReplaysCleanlyOnAFreshEmptyDatabase` 继续全量绿）。

## 五、下一阶段 SSE 改造建议（衔接 INT-2F-3 §7）

1. 在 `AiSseGatewayService.openGet/openPost` 现有 Flux 生命周期内加周期主库复核（复用 `LoginSessionService.isSessionActive`），有效观测租期 L=3s、查询超时 Q≤1s、取消上界 5s；空闲流也跑定时器。
2. JPA 查询放有界阻塞池，单流在途查询≤1；连接池等待 30s 不满足 Q=1，需为该路径设可测试的获取/语句期限。
3. 先红侧验证已建流与空闲流两个场景（撤销后≤3s 停止准入、≤5s 发出取消），再实现；H2 快速面 + 真实 PG + loopback 事件源分层，物理断链用真实 TCP/ASGI 链测试。
4. 前端 logout 时中止本页 SSE/轮询/重连（本轮仅清凭证与 verify 缓存）。

## 六、工作区保护核验

入场既有未提交项全部原封未动（SHA-256 与 INT-2F-3 §1 记录一致）：`scripts/freeze_gate.py`（fb834c0a…）、`apps/agentOS/tests/storage/test_freeze_gate_integrity.py`（06d23d14…）、`tmp/freeze_gate/test_durations.json`（c02e3af5…）、`docs/架构设计/架构图/…drawio` 删除保持原状、docs/audits 下 8 份未跟踪审查文档保留。本轮新增 `.tmp-tests/int2f-4a-iam-session/` 证据目录。未运行冻结门禁，未提交、未推送、未部署。

完成自测后停止，交付独立验收。
