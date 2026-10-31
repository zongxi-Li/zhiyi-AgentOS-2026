# PR-CI-01｜Backend CI 测试基座与 SSE 稳定性修复报告

状态：SELF-TESTED

任务日期：2026-10-31；实际验证跨至 2026-11-01（Asia/Shanghai），文件名按任务要求保留日期。

## 1. 起始 Git 现场与变更边界

- 仓库：`zongxi-Li/zhiyi-AgentOS-2026`；分支：`master`。
- 起始 HEAD：`9cc6e432b56e6b9164cf7ee88f9eb5edf32239b3`。
- 起始 `git status --short`、`git diff --cached --name-status`、untracked 列表均为空；工作区干净。
- 仓库及检查过的上级目录未发现适用的 `AGENTS.md`。
- 本轮仅修改 Backend 测试基座、相关测试、Backend CI Workflow 与本报告。生产 Java 源码、POM、UI 源码差异均为空。
- 最终 HEAD 仍为上述基线，暂存区为空；未 Commit、Push、Merge，未触发远端重跑。
- 用户随后明确授权仅恢复 18080 本地开发实例。该运行态恢复独立记录于 7.1，没有扩大本轮源码改动范围。

## 2. GitHub CI 原始证据

最新失败 [Run 41211809602 / Job 124568193426](https://github.com/zongxi-Li/zhiyi-AgentOS-2026/actions/runs/41211809602/job/124568193426)：

```text
Runner: Ubuntu 26.04.1 / ubuntu-26.04
initdb (PostgreSQL) 18.6 (Ubuntu 18.6-1.pgdg26.04+2)
ZHIYI_PG_BIN: /usr/lib/postgresql/18/bin
FATAL: could not create lock file "/var/run/postgresql/.s.PGSQL.37857.lock": Permission denied
Tests run: 589, Failures: 1, Errors: 20, Skipped: 0
Package production jar: skipped
```

该 Run 的唯一 failure 实际位于 `SseSessionRevocationEndToEndTest` 原第 247 行：等待第三条流的 `invalidated` latch 返回 false，**尚未到达后面的 active Gauge 断言**。日志还记录了缺少 error consumer 的 `ErrorCallbackNotImplemented`，其原因是 SSE GET 返回 `401 Unauthorized`。

基线早于 02B 的 [ae709af / Run 41202556470](https://github.com/zongxi-Li/zhiyi-AgentOS-2026/actions/runs/41202556470) 已存在同样的 20 项 PostgreSQL 基座错误，并有另一项 failure：

```text
AgentOsEventControllerTest.copilotStreamUsesTheExistingPostSseGateway
Expected: a string containing "partial"
     but: was ""
Tests run: 589, Failures: 1, Errors: 20, Skipped: 0
```

因此，本轮没有把既存 Backend CI 故障归因为 PR-UI-02B。

原始日志保留在本机证据目录 `C:\Users\LZX\AppData\Local\Temp\pr-ci-01`：`github-41211809602.log`、`github-ae709af.log`。读取最新 Run 的 job/steps/logs，同时用 GitHub CLI 保存原始日志供复验。

## 3. PostgreSQL 环境与版本决策

### 3.1 保留 15.x 合同

既有 `NativePostgres` / `PostgresContainerBase` 声明 PostgreSQL 15.x，Windows 同源依赖为 PostgreSQL 15.19。原 Workflow 使用 `ubuntu-latest`、安装无 major 的 `postgresql` 元包，再选最高版本目录，实际漂移到了 Ubuntu 26.04 / PostgreSQL 18.6。

本轮固定 `runs-on: ubuntu-24.04`，使用 [PostgreSQL 官方 PGDG Ubuntu 软件源](https://www.postgresql.org/download/linux/ubuntu/)和独立 `signed-by` 公钥，明确安装 `postgresql-15 postgresql-client-15`，设置 `/usr/lib/postgresql/15/bin`。CI 输出软件包来源及版本，并检查 `initdb`、`postgres`、`pg_ctl` 均为 15.x。minor 随 15 系列安全更新，不把原合同改成 18.x。

测试基座也验证三个二进制的真实版本和 JDBC `SHOW server_version`；错误 major 或未知版本明确 `BLOCKED_BY_PG`。删除原来查询版本失败时仍返回“15.x”的假定。Linux 自动定位只选 15 目录，Windows 自动定位只选 `postgresql-15.*`；显式配置和 PATH 候选同样必须通过实际版本检查。

运行时依赖树实测且未修改 POM：Spring Boot 3.2.0、Spring MVC 6.1.1、PostgreSQL JDBC 42.6.0、Flyway 9.22.3、Reactor Core 3.6.0、Reactor Netty HTTP 1.1.13、Micrometer 1.12.0、Lettuce 6.3.0.RELEASE、Awaitility 4.2.0。Flyway 在真实 PostgreSQL 15.19 上完成当前 12 项迁移、fresh 数据库重放与 Hibernate validate。

### 3.2 Socket 所有权与生命周期

[PostgreSQL 15 连接配置](https://www.postgresql.org/docs/15/runtime-config-connection.html)中，TCP 监听地址与 Unix Socket 目录是不同设置。只设置 `listen_addresses=127.0.0.1` 并不能阻止发行版默认使用 `/var/run/postgresql`。

修复后，Linux 在本次随机临时 cluster 根目录内创建 `socket`，权限为 owner `0700`，显式传入 `unix_socket_directories`；目录列表使用引号保护含空格、逗号的父路径。Windows 不创建该目录，也不传 Unix Socket 参数。随机 TCP 端口仍绑定 loopback，Ready 仍以真实 JDBC 连接判断。

生命周期继续是：本机 15.x 二进制校验 → 自有临时 root → `initdb` → 自有 `postgres` → JDBC Ready / 实际版本 → 建库 → Flyway / Repository / IAM / Redis 测试 → `pg_ctl stop -m fast` → 等待进程结束 → 删除本次临时 root。`initdb`、版本检查、`pg_ctl` 等待均有上界；中断/超时回收本轮创建的子进程，启动失败不被清理异常覆盖，清理异常作为 suppressed 保留。端口分配放入可清理的启动范围，避免分配失败留下空 root。

新增真实实例测试验证 TCP、真实版本、Linux Socket 文件与权限、Windows 无 Unix 参数、含空格/逗号路径、第二个数据库、重复 close、进程死亡、目录删除及关闭后 JDBC 连接失败。另在服务器已 Ready 后故意使用非法数据库名，验证失败会停止实例并移除临时目录。二进制缺失与启动失败继续显式失败，无 skip、H2 替代或容器替代。

### 3.3 本地两种环境

| 项目 | Windows | Linux 本地验证 |
|---|---|---|
| 系统 | Windows 11 | Ubuntu 24.04.3 / WSL2，uid 1000 `lzx` |
| Java / Maven | Temurin 21.0.11 / 3.9.12，编译 release 17 | Ubuntu OpenJDK 17.0.20.1 / 3.9.12 |
| PostgreSQL | 15.19，既有 ZhiyiNative 依赖 | 15.19-1.pgdg24.04+2，官方 PGDG 软件包 |
| Redis | Memurai 4.1.2，Redis API 7.2.5 | Redis 7.0.15，Ubuntu 软件包 |
| 生命周期 | 测试 JVM 自管随机端口实例 | 测试 JVM 以普通用户自管随机端口实例 |

Linux 二进制/JDK 解包在 `/home/lzx/.cache/pr-ci-01-native`，软件包校验值与软件源索引核对；未用 Docker 或 Testcontainers。构建输出独立于 Windows `target`，两种平台使用相同工作区源码。

## 4. 原 20 项 Integration Error 的直接根因

| 受影响类 | 原 Errors | 修复后定向结果（两种平台） |
|---|---:|---|
| PostgresMigrationIntegrationTest | 4 | 4/4 |
| PostgresRepositoryIntegrationTest | 7 | 7/7 |
| RoleCacheRedisIntegrationTest | 6 | 6/6，包含真实 Redis 停止/重启降级路径 |
| SessionRevocationPostgresIntegrationTest | 2 | 2/2 |
| SseSessionRevocationPostgresTest | 1 | 1/1，真实 PostgreSQL 会话撤销 |
| 合计 | 20 | 20/20；另有新增 NativePostgresTest 4/4 |

这些 Errors 均沿共享 `PostgresContainerBase` 的静态初始化失败传播；Redis 测试也继承该基座，尚未能进入自身测试逻辑。第一个异常是 Socket 锁文件权限错误，随后出现 `ExceptionInInitializerError` / `NoClassDefFoundError`。版本漂移是并存的测试合同缺口；这 20 项错误的共同直接根因是默认 Socket 路径权限。

在 Linux 普通用户下，用同一 PostgreSQL 15.19 的原启动参数、root-owned `0755` 的 `/var/run/postgresql`，已复现 `Permission denied`，退出码 1。这也证明只修正 major 仍不能关闭 Socket 故障。修复后的真实实例测试在两平台均通过，Linux 自有 Socket 的权限与文件存在性也由测试断言。

## 5. 两项 SSE 故障的根因与修复

### 5.1 POST SSE 空响应体

Controller 返回 `Mono<ResponseEntity<Flux<ServerSentEvent<String>>>>`。第一轮异步完成表示外层响应实体可用；随后 SSE body 的异步写出可开启另一轮请求。旧测试只做一次 `asyncDispatch` 就读 body，合法的迟到事件会使它读到空字符串。

新增受控 `Sinks.One` 回归：确认 Flux 已订阅，但未投递事件时第一轮 dispatch 的 body 确实为空；投递 `partial` 后，等待 MVC 的实际 `getAsyncResult` 完成并做最后一次 dispatch，再断言最终 body 包含 `partial`、请求异步生命周期结束、gateway 只被调用一次。原 GET `hello`、POST `partial` 与路由委托断言保留。使用真实 MVC 写出完成信号，没有固定 Sleep、协议修改或删除断言。

参考 [Spring 官方异步测试说明](https://github.com/spring-projects/spring-framework/blob/main/framework-docs/modules/ROOT/pages/testing/mockmvc/hamcrest/async-requests.adoc)与[流响应测试说明](https://github.com/spring-projects/spring-framework/blob/main/framework-docs/modules/ROOT/pages/testing/mockmvc/hamcrest/vs-streaming-response.adoc)；实际行为由本仓库 Spring 6.1.1 的受控回归证明。

### 5.2 撤销测试及 Active Streams 观测竞争

旧 `openStream()` 在 WebClient `subscribe()` 后立刻返回。该调用并不保证 HTTP 请求已完成认证、网关已订阅、受保护事件已到达。测试随后立即 cancel 两条请求并 logout，第三条请求可能在撤销后才进入过滤器，安全地返回 401，而不是建立流后收到 `auth.invalidated`。旧订阅没有 error consumer，401 变成后台丢弃错误，主测试只能等到 latch 超时。

此外，客户端 `dispose()`、收到终止事件、客户端 HTTP 完成、网关 `doFinally` 和上游 TCP 关闭是不同的观测时点。旧测试固定 Sleep 300ms 后读取 Gauge，也不能证明清理已经完成。

修复后的测试：

1. 每次打开流都等到真实受保护事件交付，并记录 error / terminal signal；建连错误立即成为测试失败。
2. 三条流实际建立后核对 opened 增量 3、active 增量 3；重复 dispose 前两条，等待取消增量精确 2、active 精确剩 1，再撤销第三条。
3. 等待 `auth.invalidated` 和 HTTP `ON_COMPLETE`，随后以有界条件等待服务器指标：completed 精确增加 1、cancelled 精确增加 2、active 精确回到原零水位；终止事件只能出现一次。
4. 每个用例的 `@AfterEach` 清理全部已打开订阅，并验证 `opened = completed + cancelled`、active 为零，以及对应真实上游 HTTP handler 已关闭，防止用例间污染。
5. 原撤销 ≤5000ms、撤销后禁止受保护事件、撤销后重连 401、另一账户持续交付等安全断言保留；用完成/事件条件替代断言前的固定休眠。

本轮没有得到生产资源泄漏反例，未修改 `AiSseGatewayService`、`SessionRecheckGate` 或正式 SSE 事件协议。新增 `AiSseGatewayLifecycleTest` 通过真实 WebClient SSE 解码和生产网关分别覆盖 Complete、上游 Error、重复 Cancel、Session Revocation：一条 opened 流精确释放一次，active 归零，上游清理一次。上游 Error 保留现有 `AI_STREAM_INTERRUPTED` 终止协议。

## 6. 修复前反例与测试自身审查

- 未改测试在 Windows 首轮 7 项及额外 5 轮双方法运行中均通过，不能据此否定 CI 竞争。
- 受控旧时序反例 A：保持 body 的 `Sinks.One` 未交付，旧单 dispatch 的 `partial` 断言稳定失败，body 为 `""`。
- 受控旧时序反例 B：只把 SSE GET 的实际发送关在释放信号之后，先完成 logout 再释放请求；服务器返回真实 401，旧 `invalidated` 断言稳定失败。未修改服务器安全规则，也没有用 Sleep 制造通过。
- 两个受控反例同次 Maven 执行得到 `Tests run: 2, Failures: 2, Errors: 0`，退出码 1。诊断源代码、原始失败 XML/TXT 和日志保留在证据目录的 `*.controlled-before.java`、`controlled-before-reports/`、`controlled-before-sse.log`。最终源码已移除诊断门闩，保留正确的确定性回归。
- 新增网关生命周期测试开发时，冷 Flux mock 会让 WebClient 错误释放动作看起来像第二次真实上游订阅；最终 mock 明确执行真实 HTTP body 的一次订阅语义，第二次消费被拒绝，真实资源的一次清理断言保留。测试也像生产 Spring singleton 一样保持 Gauge 状态所有者存活，避免仅因测试 helper 局部对象被 GC 而得到 NaN。两个测试夹具问题的失败日志保留，没有据此猜测修改生产代码。
- POM、Surefire excludes / excludedGroups 均未修改；既有 performance tag 排除保持基线口径。没有 `@Disabled`、新增跳过、断言降级、强制 Gauge 重置或负数归零。598 项为原 589 项加 9 项新测试，最终 skipped 为 0。

## 7. 最终验证结果与打包现场

以下最终门禁对应同一份源码快照。每个命令退出码、测试数均从原始输出与 Surefire 报告核对。

| 验证 | Windows | Ubuntu 24.04 / JDK 17 |
|---|---|---|
| PG / Redis / PG 会话撤销定向 | 24/24，exit 0 | 24/24，exit 0 |
| SSE Controller 定向 | 4/4，exit 0 | 4/4，exit 0 |
| SSE / Gate / Lifecycle 定向 | 27/27，exit 0 | 27/27，exit 0 |
| 原 POST SSE 方法，单独 JVM 重复 | 5 轮，各 1/1 | 5 轮，各 1/1，exit 0 |
| 原 Cancel/Close 方法，单独 JVM 重复 | 5 轮，各 1/1 | 5 轮，各 1/1，exit 0 |
| 完整 `mvn -B -ntp test` | 598 项，118 suites，0 failure/error/skip，exit 0 | 598 项，118 suites，0 failure/error/skip，exit 0 |
| 默认 `target` 的标准 JAR 打包 | FAIL：已有开发进程占用目标 JAR，repackage 重命名失败 | 两平台输出隔离，未覆盖 Windows target |
| 独立输出目录的生产 JAR 打包 | PASS，exit 0 | PASS，exit 0 |

Windows 全量测试耗时 1:55；正式参数真实网络撤销到终止事件 2586ms，PostgreSQL 权威下 2777ms，原 ≤5000ms 断言均通过。Linux 全量结果及耗时：完整测试 3:31；真实网络撤销 2591ms、PostgreSQL 权威下 2764ms，原 ≤5000ms 断言均通过；完整打包 1:50。

Windows 完整测试使用原命令；默认打包也实际执行了 `mvn -B -ntp package -DskipTests`，失败日志没有删除。随后使用仓库原有的 `zhiyi.build.directory` 参数，在新目录重新编译并打包：

```powershell
cd apps/backend
mvn -B -ntp test
mvn -B -ntp package -DskipTests "-Dzhiyi.build.directory=$env:TEMP\pr-ci-01\windows-package-target"
```

Linux 以普通用户在相同 `apps/backend` 源码目录执行同样的 test/package 目标，附加独立输出与缓存定位参数：

```bash
mvn -B -ntp \
  -Dmaven.repo.local=/mnt/c/Users/LZX/.m2/repository \
  -Dzhiyi.build.directory=/home/lzx/.cache/pr-ci-01-native/backend-target test
mvn -B -ntp \
  -Dmaven.repo.local=/mnt/c/Users/LZX/.m2/repository \
  -Dzhiyi.build.directory=/home/lzx/.cache/pr-ci-01-native/backend-target package -DskipTests
```

定向选择器依次为 `NativePostgresTest,PostgresMigrationIntegrationTest,PostgresRepositoryIntegrationTest,SessionRevocationPostgresIntegrationTest,RoleCacheRedisIntegrationTest,SseSessionRevocationPostgresTest`；`AgentOsEventControllerTest`；`SseSessionRevocationEndToEndTest,AiSseGatewayLifecycleTest,AiSseGatewayServiceTest,AiSseGatewaySessionRevocationTest,SessionRecheckGateTest`。两项重复测试分别用 `-Dtest=类名#方法名 test`，不是合并成一次后称多轮。

`-DskipTests` 仅用于完整测试通过后的生产包步骤。两份 JAR 均核对 Boot `JarLauncher` / `Start-Class`、生产主类的 class major 61（Java 17）及测试基座未打入 JAR。

| 产物 | SHA-256 |
|---|---|
| `%TEMP%\pr-ci-01\windows-package-target\kinlin-backend-1.0.0.jar`，79,100,951 bytes | `c350ccf5505f950d81a8b9e472a4085b4ca24a15db7fe123e272aa176fe3f447` |
| Linux `/home/lzx/.cache/pr-ci-01-native/backend-target/kinlin-backend-1.0.0.jar` | `f062744386b6232c91054aacc3270b2c6249ce06c8bd23bd49627bc49c9ebd9c` |

源码校验清单覆盖 backend src、相关 POM、Workflow 共 480 个文件。验证前清单 SHA-256 为 `7655F5C2332CEDD46D9EF8B79AF7744F8C9CE8AB8DC9AFF0CC50B939EDB61FEF`；最终校验：480 个路径及内容完全一致，0 差异，清单 SHA-256 与验证前相同。报告不属于测试输入，报告编写后重新做 `git diff --check` 与新增文件空白检查。

Workflow 的 YAML 解析、安装 step 的 `bash -n` 均通过。运行时依赖树已保存。两平台原生测试 PostgreSQL / Redis / Memurai 的临时实例未发现残留；Windows 既有 default 环境中的 PostgreSQL、Redis 等进程保持原身份。

### 7.1 Windows 默认 target 与既有开发实例

默认打包失败前 Maven 已写出普通 JAR，随后无法把它重命名为 `.jar.original`。只读检查发现既有 PID 38960（2026-10-31 20:10:17 启动）使用该目标，监听 `127.0.0.1:18080`；独占读取检查也确认文件被占用。另一个发行包实例使用 `D:\build-test` 下不同的 JAR。

独立目录打包成功不能冒充原路径命令成功。该失败日志为 `verified-windows-package.log`，成功记录为 `verified-windows-isolated-package.log`。标准打包前未先检查运行产物占用，使这次验证写出的普通 JAR 留在原运行路径；该文件为 795,143 bytes，不含 `BOOT-INF` 和可执行 `Main-Class`。直接、不经代理的 `18080/health` 返回 500，既有 Java 日志进一步记录 `NoClassDefFoundError / ClassNotFoundException: OperationalQuery$BasicHealth`。这属于本轮本地打包操作与运行产物的冲突，独立于原 GitHub CI 故障。

用户明确授权后，先保存原启动参数、工作目录和 93 项环境变量（环境快照仅以当前用户 DPAPI 加密保存在本机证据目录），再使用既有 native runtime 的身份校验、控制锁、停止与隐藏启动机制，只恢复 Java 进程。旧 PID 38960 优雅停止超时，按已核验身份终止（stopMode=`terminated`）；恢复已验证的完整 JAR，沿用原参数/工作目录/环境，新 PID 为 45128，18080 的 `/health`、`/health/ready` 及 actuator readiness 均为 UP，直接 HTTP 核验为 200。

运行时登记只更新 java 的进程记录。读回新进程的 93 项环境变量，与原快照逐项比较为 0 差异。其余 7 项服务 PID 及身份不变；environment、credentials、grants、.env 和 terminal 配置的哈希未变；users、roles、conversations、messages、sessions、migration 表计数前后一致。未重新初始化数据库、轮换凭据或恢复整套服务。原失败普通 JAR 保留为证据目录 `target-before-recovery.jar`，恢复回执为 `runtime-recovery.json`，完整生产包哈希与上表 Windows 独立产物一致。

## 8. 修改文件与必要性

| 文件 | 必要性 |
|---|---|
| `.github/workflows/backend-ci.yml` | 固定 Runner 系统、明确 PGDG 15.x 安装和版本/来源输出，保留原测试与打包顺序 |
| `apps/backend/src/test/java/com/kinlin/ai/integration/NativePostgres.java` | 私有 Linux Socket、跨平台参数、真实版本检查、启动/关闭等待与失败清理 |
| 同目录 `PostgresContainerBase.java` | 明确失败提示中的安装包为 postgresql-15，保留共享基座与 profile 合同 |
| 同目录新增 `NativePostgresTest.java` | 4 项真实实例生命周期、失败清理、版本和跨平台参数回归 |
| `apps/backend/src/test/java/com/kinlin/ai/controller/AgentOsEventControllerTest.java` | 等待 MVC body 完成，增加迟到 body 回归，保留 payload/path 断言 |
| `apps/backend/src/test/java/com/kinlin/ai/integration/SseSessionRevocationEndToEndTest.java` | 真正建连后再撤销；观测错误、完成、真实清理与精确指标；逐用例隔离 |
| `apps/backend/src/test/java/com/kinlin/ai/gateway/AiSseGatewayLifecycleTest.java` | 4 项生产网关终止路径回归，不修改网关协议或计数代码 |
| 本报告 | 原始失败、反例、最终门禁、源代码快照及未验证边界 |

生产源码修改清单为空；PR-UI-02B、WorkflowRuntime、Scheduler、ExecutionBackend、业务数据与正式 SSE 安全规则均不在本轮源码改动中。

## 9. 仍未验证的边界

1. **没有新的 GitHub Actions 通过记录。** 本轮按要求不 Commit/Push，远端仍是旧基线；本地 Ubuntu 24.04 WSL2 的真实测试不能冒充 Azure Hosted Runner 上的新 Run。
2. Workflow 的 PGDG 签名源配置已静态检查，实际使用了官方 PGDG 15.19 二进制验证，但尚未在全新 GitHub Runner 中执行这次安装 step。CI 的 Temurin 17 与本地 Ubuntu JDK 17 的 vendor/minor、内核和文件系统仍有差异，需要独立复验。
3. 正常 close、Ready 后失败回收、目录移除已经在两平台实测；所有操作系统级不可终止/强杀失败情形未做穷尽故障注入，不能声称覆盖全部外部进程故障。
4. Windows 默认 target 的失败及后续单独授权的恢复列于 7.1。运行实例仍会持有原路径，后续本地门禁应使用独立构建目录；本次恢复没有把原路径打包失败改写为通过，也没有替代 CI 复验。

## 10. 独立复验结论与证据入口

**SELF-TESTED，可交独立复验。** 原 20 项集成错误的共享 Socket 根因已通过 Linux 原始反例及两平台真实数据库测试关闭；两项 SSE 竞争已有确定性回归和两平台各 5 轮独立重复结果，完整测试均为 598/598，生产 JAR 均成功产出。生产源码、安全断言和 SSE 协议保持原合同。

尚需独立复验实际 GitHub Runner 的安装和完整 workflow；本轮没有新的远端 CI 通过记录，没有 Commit、Push 或 Merge。18080 仅按用户后续明确授权完成本地恢复，该动作没有被计为 GitHub CI 或部署验收。

本机证据目录：`C:\Users\LZX\AppData\Local\Temp\pr-ci-01`。最终日志为 `verified-windows-integration.log`、`linux-integration.log`、`verified-{windows,linux}-controller.log`、`verified-{windows,linux}-sse.log`、各 `*-repeat-1` 至 `*-repeat-5.log`、`verified-{windows,linux}-full.log`、`verified-windows-isolated-package.log`、`verified-linux-package.log`。Windows 全量 Surefire 原件另存 `verified-windows-full-reports/`；Linux 全量报告保留在独立 build directory 的 `surefire-reports/`。源码清单为 `source-before.json` / `source-after.json`，版本证据为 `dependency-tree.log`，产物证据为 `windows-jar-evidence.json` / `linux-jar-evidence.json`。
