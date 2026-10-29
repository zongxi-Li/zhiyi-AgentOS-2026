# PR-DOCKER-REMOVAL 完全放弃 Docker：迁移与清除实施/验收记录

日期：2026-10-29（Asia/Shanghai）。基线：`master`（批次 1 起点 `4374f744` 之前）。
性质：实施与验收证据；运行形态权威仍为 [N03 README](../../ops/scripts/infra/windows/native/README-N03.md)。

## 终态

- **日常运行**：N03 Windows 原生持久栈（本机 PostgreSQL 15.19 + Memurai + Java/Python/Vite + Electron），不调用 Docker。
- **部署形态**：原生运行 + Electron 安装包（安装包业务流仍受下述残余风险约束）。
- **测试底座**：后端集成测试由测试 JVM 自管 PostgreSQL/Redis 临时实例；不依赖 Docker/Testcontainers。
- **仓库**：Compose、Dockerfile、nginx、容器部署/发布脚本、Testcontainers 依赖与相关测试全部删除。
- **本机**：本项目 5 个容器与 7 个项目网络已删除；Docker Desktop 4.52.0 保留（项目所有者明确后续用于其他项目），
  旧项目数据卷保留在 Docker 内。**项目不再随 Docker 启动而拉起任何容器。**

## 批次与提交

| 批次 | 内容 | 提交 |
| --- | --- | --- |
| 1 | Docker 数据一次性迁移（PG/agentOS/uploads，冷备 + 回执 + 行数/摘要对表） | `4374f744` |
| 2 | 运行链切原生 18080；N02 Docker 桌面入口退役；停机 hardening；Electron 独立 userData | `50399acb` |
| 3 | 后端集成测试改自管 PG/Memurai；删 Testcontainers；CI 改 apt 原生服务 | `bccc8e90` |
| 4a | 删除 Compose/Docker 构建、部署与发布资产 | `7d369ac8` |
| 4b | 应用侧删 Dockerfile/nginx/容器 profile；TUI 直连 N03；删 LHTB Docker 适配 | `57efb829` |
| 4c | README/文档索引改原生；历史容器文档加废弃声明 | `2eac7530` |
| 5 | 本项目容器/网络清除；Docker 关闭状态下 N03 与测试验收；本记录 | （本提交） |

## 数据迁移（批次 1）

归档：`D:\kinlin-archive`（4155 文件，17.04GB，迁移回执含逐文件 SHA-256）。

| 数据 | 结果 |
| --- | --- |
| PostgreSQL `kinlin_ai` → N03 `zhiyi` | 7 表行数逐一一致（43 用户 / 97 消息 / 17 会话 / 14 会话凭证），Flyway V1–V11 完整 |
| agentOS 14 个 SQLite → `home/data` | integrity_check 全 ok、SHA-256 校验；166 Mission / 199+143 Run / 1334 语义任务 / 1186 执行步 / 113 工件 / 3721 溯源链 |
| uploads | 4 文件并入 |
| 容器绝对路径 `/app/data` 残留 | 全库扫描零命中，无需重写 |

功能实证：容器时代真实账号在原生栈登录成功（200 + JWT），历史会话原文返回。

## 运行链切换（批次 2）

- Vite 代理默认 `9050(Docker 网关) → 18080(N03 Java)`，删除 `proxyThroughHostGateway` 特例。
- Electron main/app-assets/前端平台层默认 API origin → `18080`；`.env.electron` 同步。
- N02 退役：`desktop_runtime.py` 收敛为 `spawn_app/show_desktop/close_desktop/wait_until`；
  删除 `desktop.ps1`、`README-N02.md`；`_common.ps1` 等容器开发脚本随后在批次 4 删除。
- 停机硬化：优雅信号失败后只对 `native.owned()` 核验过的进程树 `terminate/kill`，回执记录 `stopModes/escalated`。
- 启动失败取证：`up-failure.json` 先落原始栈 + 服务日志尾，再清理，清理失败不掩盖首因。
- N03 桌面固定 `home/electron` userData，消除与热更新链的 Electron 单实例锁冲突。
- 热更新链显式剥离外部注入的 `ELECTRON_RUN_AS_NODE`。

真机冒烟（2026-10-29）：热更新链 `start-desktop-hot.ps1` 窗口打开、Vite 代理 `/api/health/ready` 200；
N03 `up -Desktop` 窗口 + CDP 19222 + 代理 200；两次 down 均 PASS。

## 测试底座（批次 3）

- `NativePostgres`：`ZHIYI_PG_BIN` → `%LOCALAPPDATA%\ZhiyiNative\dependencies\postgresql-15.19\pgsql\bin`
  → CI `/usr/lib/postgresql/*/bin`；临时目录 `initdb` + 随机 loopback 端口，JVM 关闭 `pg_ctl stop` 清理。
- `NativeRedis`：Windows 用 N03 同源 Memurai 4.1.2，Linux/CI 用 `redis-server`；临时配置无 AUTH；`stop()/restart()` 同端口。
- 迁移重放改为同一实例第二个全新 database（fresh 语义保留）；Redis 降级测试改基座 `stopRedis()`。
- `pom.xml` 删除 Testcontainers；`backend-ci.yml` apt 安装 postgresql/redis-server 并导出 `ZHIYI_PG_BIN`。

验收：Docker Desktop 关闭、引擎不可达状态下，`PostgresMigrationIntegrationTest + RoleCacheRedisIntegrationTest`
10/10 通过（PostgreSQL 15.19 临时实例、Memurai 7.2.5 协议）；全量 `mvn test` 571 例中仅 1 例既存守卫失败（见残余）。

## 仓库清零（批次 4）

删除：根 `compose.yaml/.dockerignore/.env.example`、`.config/compose`、`.config/env`；`ops/docker`、`ops/deploy`、
`ops/scripts/release`；镜像/预检/备份/恢复/schema 审计等容器模块与测试；Windows compose ps1 全套；
dev/deploy/rollback/setup-dev-env 与 4 个退役存根；三应用 Dockerfile/nginx/entrypoint；
`application-compose.yml`；Testcontainers 依赖；LHTB Docker benchmark；TUI Docker 启动分支。

全仓 `docker` 残留审计（tracked 源码/配置，排除历史文档与语料）仅剩：
`.github/workflows/backend-ci.yml`（“零 Docker”说明）、`README.md`（“不需要 Docker / 零 Docker”说明与历史 RFC 链接）、
`apps/agent/app/tools/terminal.py`（危险命令正则，保留项）、`ops/.../README-N03.md`（“无 Docker”环境名）、
`ops/.../README.md`（“No Docker”说明）、`ops/.../migrate_from_docker.py`（迁移工具，保留项）。
RAG 语料与历史容器文档按计划保留。

验证：前端 vitest 108 文件 / 726 例；ops 31 例；agentOS 架构门禁 16 例；后端 571 例（1 例既存失败）。

## 本机收尾（批次 5）

- 2026-10-29 22:57 Docker Desktop 重新启动后，`unless-stopped` 自动拉起本项目 5 容器；立即执行：
  `docker rm -f` 移除 `kinlin-win-p1-001-{ai-service,backend,frontend,postgres,redis}-1`，并删除 7 个项目网络。
- 随后 `docker desktop stop`：无 Docker 进程、`docker-desktop` WSL 发行版 Stopped、引擎不可达。
- Docker Desktop 4.52.0 与 `D:\docker mirror\DockerDesktopWSL\disk\docker_data.vhdx`（初始 33.63GB，
  后续压缩见下）保留，供其他项目使用；本项目不再有容器/网络，故 Docker 启动不会复活本项目栈。
- 项目数据卷先保留复核（18 个，p1-001 13 + p1-002 5，约 19.3GB）；项目所有者随后确认“全部删除”：
  - 删除前把 3 个未归档旧卷补冷备到 `D:\kinlin-archive\legacy-volumes-20261029\`：
    `agentos_data_v11`（26.98MB，43 entries）、`agentos_wkn_data_v1`（0.70MB，22 entries）、
    p1-002 `postgres_data_v11`（6.51MB，1345 entries）；`SHA256SUMS.txt` 已落盘，tar 可正常列出。
  - 随后 `docker volume rm` 删除全部 18 个 `kinlin-win-p1-00{1,2}_*` 卷，无失败。
  - 剩余 10 个卷（1.031GB）均属其他项目/无主卷：`vitatrace_*` 6 个、`docker_postgres_data`/`docker_redis_data`、
    2 个 0B 匿名卷；未触碰。
- 验收后观察到 Docker Desktop 被外部重新启动（`docker info` = 29.0.1）；复核 `docker ps -a` 为空、
  无 `kinlin-win-p1-001_*` 网络、10 个其他项目卷仍在。即：Docker 继续服务其他项目，但**本项目没有任何
  会随 Docker 启动而复活的容器/卷**。
- 镜像清理（项目所有者追加指令）：删除 `kinlin-ai-{service,frontend,backend,redis,postgres,debug-proxy}:dev`
  与 `testcontainers/ryuk`（含 daocloud 镜像 tag）；`docker system df` 的 Images 5.963GB → 1.001GB。
  随后按已删除 Dockerfile 的 `FROM` 归属复核，再删除 `postgres:15.17-alpine`、`redis:7.4.9-alpine`
  （含 daocloud tag）与 frontend 的 `node:22-alpine` digest 镜像；Images 1.001GB → 320MB。
  剩余 `alpine:latest`、`python:3.11-slim`、`ubuntu:20.04` 无法归属到本项目 Dockerfile，保留给其他项目。
- 磁盘压缩（追加指令）：`docker desktop stop` + `wsl --shutdown` 后
  `D:\docker mirror\DockerDesktopWSL\disk\docker_data.vhdx`：
  31.73GB（初始）→ 26.04GB（删镜像 + 首次 TRIM）→ **9.78GB（删 18 个旧卷后 shutdown）**，
  累计回收约 21.95GB；`wsl --manage docker-desktop --set-sparse true --allow-unsafe` 已将该盘转为稀疏 VHD，
  后续删除会随 shutdown 自动收缩。9.78GB ≈ 1.03GB 其他项目卷 + 0.32GB 镜像 + Docker VM 自身约 8.4GB；
  再用管理员 `Optimize-VHD` 可能小幅回收，但 `fstrim` 仅剩 40MiB 可释放，收益有限。
- Docker 重启复核：引擎 29.0.1、3 个通用镜像、10 个其他项目卷、0 容器，数据完好。

### Docker 关闭状态验收（2026-10-29 22:58–23:01）

| 项 | 结果 |
| --- | --- |
| `docker info` / Docker 进程 / `docker-desktop` WSL | 引擎不可达；无进程；Stopped |
| `persistent.ps1 up`（无 `-Desktop`） | `status=UP`，5 服务全部 alive，PG/Redis/Java readiness 全 true |
| Vite 代理 `http://127.0.0.1:15200/api/health/ready` | 200 `{"status":"UP","checks":{"postgres":true,"redis":true}}` |
| `persistent_checks.py` | PASS（Memurai 7.2.5、Lua lease 全通过） |
| `persistent.ps1 down` | PASS（全部 graceful/shutdown/pg_ctl，无 escalated） |
| 后端原生 PG/Redis 集成测试 | 10/10 PASS（临时实例端口 55600） |

结论：项目运行链、测试底座与本机启动均不依赖 Docker。

## 残余风险与待办

1. **打包 Electron 的 `/api` 前缀（高优先，打包发布前必须处理）**：前端服务层统一使用 `/api/...`，
   旧 Docker nginx 与 Vite 负责按控制器前缀重写（保留 `/api/agentos/v2` 等，其余去掉 `/api`）。
   现在打包壳直连 Java 18080 时没有这层重写，业务 API 会 404。EL-01 验收已登记“9050 网关未运行时
   业务流未验证”。建议在打包发布前二选一：Java 侧增加精确的 legacy `/api` 前缀兼容过滤器，或 Electron
   主进程提供仅 loopback 的本地重写网关；并补一组真实登录/Mission 的安装包验收。
2. **后端既存守卫失败**：`QueryProjectionArchitectureTest` 对 `AgentOsReviewController#toolApprovals`
   （`ResponseEntity<Map<String,Object>>` 动态透传）判不合格；该文件属并行 workspace/审批会话在途改动，
   已按项目所有者决定留给该会话修复，不在本次 Docker 清理中改产品代码或放宽守卫。
3. 本项目旧卷已全部删除（3 个未归档旧卷已补冷备到 `D:\kinlin-archive\legacy-volumes-20261029\`）；
   Docker 内仅剩 10 个其他项目卷（1.031GB），未触碰。vhdx 已压到 9.78GB。
4. Memurai Developer 仅限开发测试、连续运行 ≤10 天；长期生产需 Enterprise 授权与独立验收。
5. 本地 `master` 领先 `origin/master` 7 笔，未 push（遵守不 push 纪律）。
