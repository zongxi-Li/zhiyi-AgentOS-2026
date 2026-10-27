# INT-2F-2：IAM 会话撤销与 HTTP/SSE 边界

日期：2026-10-27。结论：**审计和现有认证边界验证完成；服务端会话撤销为 NOT_IMPLEMENTED，撤销目标尚未验收通过。** 没有把客户端登出、接口不存在或 JWT 过期冒充服务端撤销。没有新增 IAM、Session Store 或 SSE 管理器；按任务允许的审计路径，本阶段仅提交本报告。

## A：INT-2F-1 固化

入场 HEAD/master 为 `53eb030023dd2f2c631a222df3786dfd18fc1fa5`，暂存区为空；GitHub 与 Gitee 实时 master 均为该 SHA。`mirror` 存在 GitHub/Gitee 两个 push URL，故所有推送均使用显式 GitHub URL。

核对 INT-2F-1 报告、原始测试记录和当前文件摘要一致后，仅暂存并提交以下三个文件：

- `apps/agent/app/execution/coordinator.py`
- `apps/agent/tests/test_execution_coordinator.py`
- `apps/agent/tests/test_agentos_c2_dispatch_http.py`

提交：`cf8a2b4c493c261dbf2979f98c4d391fb9e1c285`，标题 `fix(coordinator): 清理首次运行前取消的任务句柄`；父节点为 `53eb030023dd2f2c631a222df3786dfd18fc1fa5`，文件清单严格为上述三份。未将门禁修复或未跟踪审查文档混入提交。复用了源码摘要匹配的 INT-2F-1 红绿和 85 个用例通过证据，本轮没有为固化而重复运行整套回归。

首次推送前实时 GitHub 仍为父节点，祖先关系验证通过，显式推送 `https://github.com/zongxi-Li/zhiyi-AgentOS-2026.git HEAD:refs/heads/master` 成功。推后实时 GitHub 为 `cf8a2b4c493c261dbf2979f98c4d391fb9e1c285`，Gitee 仍为 `53eb030023dd2f2c631a222df3786dfd18fc1fa5`。

## B：真实认证与控制调用链

本轮先审阅生产代码并在 `audit-before.json` 记录行为矩阵，再执行探测。不是根据历史“真实 IAM 已通过”推断有会话撤销能力。

1. 浏览器 `/auth/register`、`/auth/login` → `AuthController` → `UserService`/`UserRepository` 密码校验 → `JwtUtil.generateToken`。Token 包含 userId、username、role、sub、iat、exp，没有 sid/jti；当前没有第一类服务端登录会话身份。
2. 新业务请求携带 Bearer JWT → `JwtAuthenticationFilter` 验证签名、用户名、过期时间 → 创建 `AuthenticatedUserContext` → `SecurityConfig` 的 STATELESS/认证规则。当前 JWT context 的 tenantId 为 null，不能据此宣布多租户验收。
3. 正式 Dispatch HTTP → `AgentOsMissionController.dispatchRun/control` → 现有 `AgentOsClient` 实现/共享 WebClient → `TrustedUserContextForwarder` 从 Spring Security 重建身份头、`PythonServiceAuthentication` 提供内部服务身份 → Python `InternalServiceAuthMiddleware` → Mission owner/read/write 检查 → 原 Coordinator、Dispatch Store、Permit、Native Runtime。本轮不修改这些执行合同。
4. SSE GET `/api/agentos/v2/runs/{runId}/events` → 同一新请求认证 → `AgentOsEventController` → `AiSseGatewayService.openGet` 捕获可信用户 → 现有 Python transport → Python `/runs/{run_id}/events` 的 `load_run` 检查 → 原 RuntimeEventBroker 订阅。Java 和 Python 都在建立连接时授权，不是每个事件重新验证浏览器 JWT。
5. Java SSE 有 idle 和 absolute maximum duration，默认分别为 240000ms 和 1800000ms。`SecurityConfig` 对 ASYNC continuation 放行已授权响应；没有发现服务端会话撤销通知、持久撤销记录或每事件会话查询。这些时间限制不构成撤销承诺。

关键源码：`AuthController.java`、`JwtUtil.java`、`JwtAuthenticationFilter.java`、`SecurityConfig.java`、`AuthenticatedUserContext.java`、`TrustedUserContextForwarder.java`、`AiSseGatewayService.java`；Python `app/security/internal_auth.py`、`app/api/agentos_v2.py` 的 `stream_runtime_events`。

前端 `apps/frontend/src/services/api/auth.ts` 的 `logout()` 明确只清除 localStorage，并注明后端没有 logout 接口。应用的 `/auth/**` 实际注册映射为 login/register/verify，没有 session/logout/revoke 映射。Spring 框架默认 logout 功能不能被等同于已签发 JWT 的持久撤销；本轮没有把未知 URL 的 404 推广成所有框架行为的证明。

## 行为矩阵：修改前与修改后相同

本轮未修改生产代码，也没有改变测试预期去制造“撤销通过”。

| 场景 | 实际证据与当前行为 | 裁决 |
| --- | --- | --- |
| 正常注册、密码登录后新 HTTP 控制 | 202，上游计数一次；伪造用户头被真实登录身份覆盖 | 已核验 Java 认证/转发边界 |
| 匿名、签名篡改、已过期 JWT 新 HTTP | 401，上游控制计数为零 | 已核验，不能当作撤销测试 |
| 同类无效凭证新 SSE/重连 | 401，上游 SSE 计数为零或保持原值 | 已核验，不能当作撤销测试 |
| 服务端撤销后新 HTTP | 没有撤销权威或入口；并发 POST `/auth/logout` 均 404，保留的有效 JWT 仍返回 202 | **NOT_IMPLEMENTED**，不是拒绝通过 |
| 撤销前已建立 SSE | 无法执行真实服务端撤销，不能填 PASS；另见过期探测 | **NOT_IMPLEMENTED** |
| 撤销后 SSE 重连 | 无可验证的撤销事实，不能填 PASS | **NOT_IMPLEMENTED** |
| A 撤销 B 的会话 | 没有 session 标识和撤销 API，不能用别的权限测试或接口 404 代替 | **NOT_IMPLEMENTED** |
| 重复/并发撤销 | 两个未注册 logout 请求 404 不证明撤销幂等，两个用户的 JWT 均仍有效 | **NOT_IMPLEMENTED** |
| 已建立 SSE 跨 JWT 过期 | 初始收到 before；等待签名 Token 的真实 exp 后，新 HTTP 和重连均 401，但原连接仍收到 protected-after-boundary | 已核验连接期与请求期边界不同；不是即时失效保证 |

普通登录 Token 来自真实密码登录，不注入测试 principal。过期/短时效探测额外使用真实 JwtUtil 与隔离测试密钥构造负向 Token，不使用生产凭据，不声称这些负向 Token 也来自正常登录接口。

## 探测设施、范围及没有实施修复的原因

探测通过真实 Spring Boot 随机端口、真实 SecurityFilterChain、真实 UserService/JPA 和内存 H2 注册并登录，随后访问实际 Java Dispatch/SSE 路由。Python 上游是 loopback HttpServer 计数/事件服务，用于证明无效凭证不进入转发，以及连接是否继续交付事件。它不是 Runtime/Authority，也不执行节点或验证 Mission owner。因此正常控制 202 不能作为真实 Dispatch/Provider E2E；两个用户在该计数服务各自得到 202 不能用来判断跨用户任务访问授权。

既有 Java/Python 身份、网关和 SSE 回归另行运行；INT-2F-1 的真实 Runtime/SQLite 回归作为已匹配源码的前序执行链证据，未冒充本轮重新执行。

确认的是功能前提缺失，而不是已存在撤销实现中的分支错误。当前源码明确为无状态 JWT，未找到“撤销后新请求必须拒绝”所依赖的持久事实，或既有流即时撤销合同。没有为了产生实现差异，临时用进程字典、User.updatedAt、客户端 logout 标记或第二套 Session Store 模拟撤销，也没有擅自改变已签发 Token 的解释。

因此本轮没有修复提交、没有修复前失败/修复后通过的永久撤销回归；该项为不适用，不能宣称撤销缺口已关闭。诊断测试是现状表征，4 项通过仅表示观察结果符合当前源码，不表示任务六个撤销场景通过。探测 Java 源码和隔离 POM 已从测试源目录移至本地证据目录保存；按“没有源码缺陷只提交审计报告”的范围，不把诊断代码混入产品提交。

安全上的最小可证明行为仅是：每次新请求校验 JWT；过期/无效的新 HTTP 和 SSE 请求拒绝且不转发；已建立流受既有 idle/maximum duration 约束。主动撤销及既有流失效需要下一阶段明确权威和合同，当前不可用于要求硬撤销的生产场景。

## 实际测试命令与结果

证据根目录：`.tmp-tests/int2f-2-a29d96117f5c43589889f6c0296757e0/`。没有运行正式 566 节点冻结门禁或全量 pytest。隔离 POM 只改变 build directory，原 `apps/backend/pom.xml` 不变；所有 Maven 产物写入本轮 `maven-target`，不覆盖原 target 下历史报告。

| 阶段 | 命令/选择（完整可执行参数见同名 JSON） | cwd | 测试结果 | 真实测试退出码 | 完整墙钟 |
| --- | --- | --- | --- | --- | --- |
| 边界探测 | `mvn -o -f .int2f2-validation.xml -Dint2f2.evidenceDir=<本轮目录> -Dtest=Int2f2SessionBoundaryProbeTest test` | apps/backend | 4 / 0 failed / 0 errors / 0 skipped | 0 | 41.2923 秒 |
| 相关 Java 回归 | 同一隔离 POM，`-Dtest=JwtUtilTest,JwtPropertiesTest,AuthControllerTest,SecurityRouteMatrixTest,AuthenticatedUserTest,PythonServiceAuthenticationTest,TrustedUserContextForwarderTest,AiSseGatewayServiceTest,AgentOsEventControllerTest,AgentOsMissionControllerTest` | apps/backend | 52 / 0 failed / 0 errors / 0 skipped | Maven 0，外层预览错误见下 | 26.2254 秒 |
| Python 认证/SSE | `python run_python.py python-auth-sse apps/agent/tests/test_internal_service_auth.py apps/agentOS/tests/test_runtime_live_events.py apps/agent/tests/test_agentos_v2_api.py::test_v2_terminal_run_events_finish_without_waiting_for_a_live_publisher apps/agent/tests/test_agentos_v2_api.py::test_v2_runtime_events_endpoint_streams_http_before_publisher_finishes -q --disable-warnings` | 仓库根目录 | 14 passed，2 warnings | 0 | 12.9806 秒 |

Java 回归的 Maven 进程实际退出码为 0，JUnit XML 为 52/0/0/0，原始日志 BUILD SUCCESS。采集器已经写入退出码和前后快照，之后打印日志末尾到 GBK 控制台时发生 UnicodeEncodeError，**外层采集器退出码为 1**。两者明确区分，记录在 `console-postprocessing-issue.json`，未为显示错误重跑测试，也没有把外层退出码写成 0。

本轮总计 4 项现状表征、52 项既有 Java 回归和 14 项 Python 回归通过；不是 70 项会话撤销测试通过。无业务源码测试失败。每轮源文件 SHA-256 前后相同，详细映射见 `boundary-probe.json`、`auth-http-sse-regression.json`、`python-auth-sse.json`。

## 证据与保护结果

- `observations.json`：不含 Token/密码的场景结果；`audit-before.json`：测试前代码行为矩阵。
- `Int2f2SessionBoundaryProbeTest.java`：完整诊断源码，SHA-256 `252f2c1604f9b3669cd265bf6c1c135d3ba95ae72283121ecd6187e56055ba34`。
- `validation-pom.xml`：隔离构建 POM；原执行时位于 apps/backend，复现时应在该目录用新文件名放置副本，并采用新的证据/build 目录，不覆盖本轮产物。
- 各轮 `.log`、`.json` 与 `maven-target/surefire-reports/TEST-*.xml` 保存原始输出、真实测试退出码、计数及时间。JUnit 各文件 SHA-256 见 `verification.json`。
- 原始探测日志 SHA-256 `33e5a7c6494b8e9a3d48dda49ca7df4ecd027b3009a28ec8d0b31024022b9e0b`；Java 回归日志 `21ca6204869de1a2eac71bfa688d0d8c7755a52b1a72ceeab072d101f67a901c`；Python 日志 `c3fa4e5d4a9c97886a040cf1918a2fba78913b0b842f15b75699946c4176f18a`。
- 109 个已清点的门禁历史文件和审查文档无缺失、摘要无变化；Python 采集器保护既有临时目录，防止测试 conftest 清理旧证据。没有清空历史缓存。
- 缓存 SHA-256 保持 `c02e3af5018b675ef6bb68fb60c0370aa1e21bd5017225afa33d0cb5a5970519`。已存在的门禁脚本修改保持 `fb834c0ad42dcfa9c51e1a1dc0ad879f13d4de1493988ab85e6523cd01e96484`，门禁完整性测试保持 `06d23d14368d2a35a197e9ff886142b8cb0d4167f29b525adb168a244f9a0f83`。
- Java 生产代码、原 pom、Python 控制与执行代码没有本阶段差异。数据库为隔离内存 H2及原测试临时数据，测试密钥显式为隔离测试值。没有使用生产 Provider、凭据或数据库，也没有关闭 TLS 校验。

## Git 固化与最终回执

本阶段提交范围严格只有本报告；INT-2F-1 报告和此前所有未跟踪审查文档继续留在工作区，门禁两份修改不暂存。报告提交的父节点应为已推送的 `cf8a2b4c493c261dbf2979f98c4d391fb9e1c285`。

本报告不包含自身提交 SHA 的循环引用。报告提交可由 `git log -1 --format=%H -- docs/audits/INT-2F-2-IAM-SESSION-REVOCATION-HTTP-SSE.md` 精确定位。推送前再次核对实时 GitHub master 和祖先关系，仅向显式 GitHub URL 推送，不强推、不改 Gitee。实际最终提交 SHA、GitHub/Gitee 实时核验值及工作区状态在本轮证据目录 `git-final.json` 与最终交付消息中记录；若远端竞争推进则必须报告阻断，不能把本段当作预先宣告推送成功。

## 未解决限制及下一阶段

服务端撤销能力缺失仍是明确的生产能力缺口；本轮审计完成不关闭该缺口。建议下一阶段先定义撤销粒度（当前 Token/会话还是主体全部 Token）、旧 JWT 兼容和唯一持久撤销权威，随后在既有 IAM 内扩展，而非平行建设。

验收应分别覆盖：撤销提交后新 HTTP/新 SSE 不转发；主体隔离和并发幂等；已建流按明确截止策略停止交付并释放订阅；过期、撤销和认证故障有可区分证据。单实例可优先复用当前流在交付前/受控周期复核权威，不在没有合同的情况下引入分布式广播系统。

当前仅证明连接建立时认证以及超时边界，没有证明即时撤销、跨租户、生产多实例、真实 Provider 或完整浏览器工作流。本轮不宣布 V1 冻结，不部署，完成报告和 Git 核验后停止。
