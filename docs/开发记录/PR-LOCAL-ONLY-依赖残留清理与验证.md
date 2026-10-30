# Electron 与本地运行：依赖残留清理

日期：2026-10-30。

## 范围与结果

当前桌面宿主仅为 Electron，本地服务由 N03 管理。清理实际代码、默认配置和运维工具中的容器假设；历史文档、迁移工具、用户数据与安全规则保留。

- 删除未被当前入口引用的 `apps/backend/sync-backend-source.sh`，移除容器源码挂载、Linux UID/GID、rsync/flock 同步逻辑。
- `PROVIDER_STATE_REDIS_URL` 默认改为 `redis://127.0.0.1:16379/2`，与 N03 Memurai 的 provider-state DB 对齐；N03 仍按实际端口覆盖，功能默认仍关闭。
- 两份补账脚本必须显式传入 `--data-dir`，使用 N03 的 `workflows.sqlite3`、`identity.sqlite3`、`content.sqlite3`；导入路径由仓库位置解析，缺少数据库立即退出，不创建空库。此次未对真实业务数据库执行补账。
- 新增 Java `LocalApiPathFilter`：仅将已知旧业务根路径的 `/api` 别名映射到已有控制器，例如 `/api/auth/login` → `/auth/login`。原生 `/api/agentos/v2` 等路径保持原样。过滤器在 Spring Security 前运行，统一 URI、servletPath、pathInfo 与 Spring 路径缓存；原有认证和会话撤销继续生效。
- 删除 Vite 的重复路径重写，使开发代理与打包版直连 Java 使用同一路由规则；更新 Electron 使用说明与 CI 的过期镜像注释。

## 验证

- 本地启动与补账 CLI 测试：`python -m pytest ops/scripts/infra/tests -q -p no:cacheprovider`，33 项通过。
- Electron 前端平台测试：adapter / uiZoom，10 项通过。
- `npm run build:electron`：类型检查与生产构建通过。
- 后端路径、鉴权、会话撤销与查询投影定向测试：26 项通过。
- `mvn -B -ntp package`：后端全量 584 项通过，0 失败、0 错误、0 跳过；生成 `apps/backend/target/kinlin-backend-1.0.0.jar`，包含真实 loopback HTTP 链路测试。

中间失败保留在 `apps/backend/target/local-api-security-diagnostic.log` 与 `local-native-full-test.log` 中。首次路径包装遗漏 `pathInfo`，安全日志显示重复路径；修正后定向测试通过（`local-api-cleanup-test.log`）。首次真实 HTTP 测试将登出成功误写为 200，现按现有控制器合同修正为 204；未修改产品登出行为。最终全量通过与打包记录为 `apps/backend/target/local-native-package.log`。

## 使用与验收边界

新 jar 已构建，需在下次 N03 启动时加载；若环境配置使用自定义 jar 路径，需同步采用该新产物。本轮不重启用户环境，不运行历史数据修复，不修改本机 Docker 安装、镜像、卷或其他项目资产。

真实 HTTP 测试使用临时 Spring/H2 测试环境与随机 loopback 端口，验证 Electron Origin 的 CORS 预检、注册、登录、读取当前用户、登出和撤销后拒绝访问；它不等于 Windows 安装包的桌面人工验收，也不等于真实 Mission 执行验收。

历史 Docker 移除记录中的打包版 `/api` 风险由本次代码修复覆盖；其过去的运行与验收记录仍按原时点理解。工作区同时存在其他会话的提交和文档整理，本记录只说明本次清理及验证，不将其他改动归入本次工作。
