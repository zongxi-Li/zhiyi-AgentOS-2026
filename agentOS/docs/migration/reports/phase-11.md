# Phase 11 — 最终回归与 Hardening 登记

## Phase

Phase 11：完成迁移主链的跨层回归、真实容器只读 E2E 和架构门禁，并把 Runtime Hardening 明确登记为后续独立里程碑。

## Baseline SHA

`e553aae9fa4d837abe8282b0a7ad7640eaee63f1`

## Result SHA

本文件所在的 `12 test(agentos): 完成迁移回归与端到端验证` 提交（提交对象不能在自身内容中编码自己的最终 SHA；确切 SHA 以 `git rev-parse HEAD` 为准）。

## Changed

- 新增 `runtime-hardening-milestone.md`，登记外部调用韧性、commitId 外部传播、ExecutionValue orphan GC、五阶段故障注入、`BLACKBOARD` 和 `DEBATE`。
- 对 Kernel、Python Application、Spring、Frontend、infra/release 和 Docker 五服务执行最终回归。
- 使用短期本地签名 JWT 验证 `frontend edge → Spring security/gateway → FastAPI v2` 只读链路；未创建用户、Run 或外部数据。
- 扫描生产代码中的 `agentos.core`、旧 RuntimeGraph 和旧 `/core` API 依赖。

## Capability Impact

- `REPLACED/MIGRATED`：本轮矩阵中的保留能力完成最终回归。
- `DEFER`：timeout/retry/rate limit、commitId 外部传播、orphan GC、五阶段故障注入、`BLACKBOARD`、`DEBATE` 保持为迁移后里程碑，本阶段未宣称实现。

## Tests（命令与结果）

```powershell
$env:PYTHONPATH="$PWD\agentOS\src;$PWD\agentOS;$PWD\agent"
python -m pytest agentOS/tests -q
python -m pytest agent/tests -q
```

结果：AgentOS `142 passed`；Application `104 passed, 1 skipped`。

```powershell
mvn -q test
npm test -- --run
npm run build
```

结果：Spring Surefire 汇总 `134 tests, 0 failures, 0 errors, 0 skipped`；Frontend `24 files / 116 tests passed`，生产构建成功（`3124 modules transformed`）。

```powershell
python -m pytest scripts/infra/tests scripts/release/tests -q
docker compose --env-file .env.windows -f compose.yaml -f compose.dev.yaml -f compose.windows.yaml ps
```

结果：infra/release `49 passed`；`frontend`、`backend`、`ai-service`、`postgres`、`redis` 五服务全部 healthy。

真实只读 E2E：使用容器当前 JWT secret 生成五分钟短期测试令牌，请求 `http://127.0.0.1:18088/api/agentos/v2/runs`，得到 `200`、`total=0`、`items=[]`；secret 和令牌均未写入仓库或报告。

架构扫描：Python 生产代码不存在 `agentos.core` 导入；Frontend、Spring 与 Python 生产代码不存在旧 `/core/workflows`、`/core/plugins`、`/core/materials`、`runtimeGraph`、`dynamicPatch` 或 `bindingSwitchCount` 依赖。

## Known Gaps

- 本次 E2E 为已认证只读链路；未调用真实付费模型或联网工具。模型、工具、审核和恢复语义由 Phase 4–6 的可重复集成测试覆盖。
- Application 测试仍报告 Pydantic/Starlette/Chroma 弃用警告，以及一个 RAG mock 产生的未 await coroutine 警告；不影响当前通过结果，需后续清理。
- Frontend 构建仍报告 Sass/chunk 警告；生产依赖审计存在 `25 vulnerabilities`，需要独立依赖治理，未执行破坏性的强制升级。
- Runtime 当前没有 SSE 合同，产品状态更新沿用 HTTP/轮询。

## Architecture Deviations

- 测试数量以当前代码实收为准：Kernel 为 142，而非历史数字。
- 计划要求记录 Result SHA，但 Git 提交无法在自身 tracked 内容中包含自身最终对象 ID；因此本报告用提交标题指代自身，最终交付报告给出确切 SHA。
- 真实付费模型调用需要外部凭据并会产生外部成本，不作为自动迁移验收；Runtime 语义使用确定性适配器测试，容器 E2E 验证授权代理和真实服务边界。

## Next Phase

迁移主链完成。后续仅按 `runtime-hardening-milestone.md` 分项立项，不在本迁移分支继续混入 hardening 实现。
