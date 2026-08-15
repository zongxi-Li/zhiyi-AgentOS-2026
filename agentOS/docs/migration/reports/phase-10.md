# Phase 10 — Docker 与持久化迁移

## Phase

Phase 10：将开发与生产容器切到 wkn AgentOS 的完整源码布局、六存储路径和隔离的新数据卷，并验证真实五服务链路。

## Baseline SHA

`b629b5b9aa8a17cd39f9334b225b6086c46c1e07`

## Result SHA

由提交 `11 refactor(docker): adopt runtime/storage layout` 固化；确切 SHA 在 Phase 11 报告提交时回填。

## Changed

- ai-service 的 `PYTHONPATH` 固定为 `/app:/app/agent:/app/agentOS:/app/agentOS/src`，应用 Pack 路径改为 `/app/agent/packs`。
- 开发 compose 完整挂载 `agent/` 与 `agentOS/`；生产/开发镜像完整复制两棵树，包含真实 `agentOS/service/`。
- 显式设置 Workflow、Checkpoint、ExecutionValue、Memory、Provenance、Decision 六个 SQLite 路径，统一位于 `/app/data/agentos/`。
- AgentOS volume 从 C4 的 `agentos_data_v11` 切换为独立 `agentos_wkn_data_v1`；旧 volume 保留且未挂载、未转换、未删除。
- backup/restore 工具只识别新 volume；备份 manifest 升至 `1.2` 并标记 `wkn-3f6c536`，restore 明确拒绝 C4/旧格式备份。
- 生产 nginx 对 `/api/agentos/v2` 保留 `/api` 前缀，使请求命中 Spring v2 Gateway。
- backend 开发镜像使用 BuildKit Maven 缓存预取依赖，并把缓存复制到非 root 运行目录；重建后加载当前 Spring v2 Gateway，而不是复用旧 jar 镜像。

## Capability Impact

- `MIGRATED`：Docker 日常开发、完整 AgentOS 源码挂载、六存储持久化、v2 边缘路由。
- `DROPPED`：从 C4 `agentos_data_v11` 恢复到新 Runtime 的能力；旧卷只保留为人工备份来源。

## Tests（命令与结果）

```powershell
docker compose --env-file .env.windows -f compose.yaml -f compose.dev.yaml -f compose.windows.yaml config --quiet
docker compose --env-file .env.windows -f compose.yaml -f compose.prod.yaml -f compose.windows.prod.yaml config --quiet
```

结果：开发与生产组合配置均通过。

```powershell
docker compose --env-file .env.windows -f compose.yaml -f compose.dev.yaml -f compose.windows.yaml build ai-service frontend backend
docker build -f agent/Dockerfile -t kinlin-ai-service:phase10 .
docker build -f frontend/Dockerfile -t kinlin-ai-frontend:phase10 frontend
```

结果：开发 ai-service/frontend/backend 与生产 ai-service/frontend 镜像全部构建成功；backend 缓存修正后的重建耗时约 29 秒；生产容器 imports 与 nginx `-t` 通过。

```powershell
docker compose --env-file .env.windows -f compose.yaml -f compose.dev.yaml -f compose.windows.yaml up -d
docker compose --env-file .env.windows -f compose.yaml -f compose.dev.yaml -f compose.windows.yaml ps
```

结果：`frontend`、`backend`、`ai-service`、`postgres`、`redis` 五个服务均 `running (healthy)`。

容器内 smoke：带可信内部身份访问 `/ai/agentos/v2/runs` 返回 `200` 和空分页；六个 SQLite 文件均已在新 volume 创建。边缘 `/api/agentos/v2/runs` 未认证请求返回 `401`；使用短期本地签名 JWT 经 `frontend → Spring → FastAPI` 访问同一路由返回 `200`、`total=0`，确认当前 v2 Gateway 与认证代理链真实生效。

```powershell
python -m pytest scripts/infra/tests scripts/release/tests -q
```

结果：`49 passed`。

## Known Gaps

- 本阶段没有创建业务 Run，模型/联网工具的真实付费调用仍由应用凭据和用户操作触发；Runtime 集成由 Phase 4–6 测试覆盖。
- frontend 生产镜像构建的 `npm ci` 报告现有依赖树有 `25 vulnerabilities`；本迁移未执行可能引入破坏升级的 `npm audit fix --force`，需单列依赖治理工作。
- Runtime 当前无 SSE 合同，容器链保持 HTTP/轮询。

## Architecture Deviations

计划示例只列三段 `PYTHONPATH`，但真实应用包位于仓库 `agent/app`，完整树在容器中位于 `/app/agent`；因此增加 `/app/agent`，否则 `import app` 无法成立。该偏差来自真实目录，而非兼容层。

## Next Phase

Phase 11：登记迁移后 Runtime Hardening milestone，执行跨层最终回归与架构门禁，不实现 hardening 条目本身。
