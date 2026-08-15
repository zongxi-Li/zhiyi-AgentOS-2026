# Phase 8 — Spring Gateway 迁移

## Phase

Phase 8：将 Spring 收束为 AgentOS v2 的鉴权、作用域、DTO 校验、HTTP 代理与错误映射边界。

## Baseline SHA

`1bee526d6624d945d9aff618cb16eb0cd7b2c773`

## Result SHA

`a56a9979f84891fe3ae69912ee45eee90f78965e`

## Changed

- 唯一公开前缀改为 `/api/agentos/v2`，只代理 Python `/ai/agentos/v2`。
- 显式代理 Run、Graph、Output、Trace、Provenance、Checkpoint 和 Review，不再提供旧 `/core`、`/agentos`、`/ai` 三重映射。
- 删除 `WorkflowProgressResponse`、旧 async start DTO 及其中的动态图/绑定/降级伪投影。
- 新增创建与审核请求 DTO；标题、幂等键、审核操作和 decision 在网关边界校验，状态语义仍由 Python 解释。
- 2xx/4xx 状态按合同转发；上游 5xx 统一映射为 502，正文不回传；网络故障映射为 503。
- user/tenant/trace scope 继续由现有 Spring Security 与 `TrustedUserContextForwarder` 注入，客户端身份头不会透传。

## Capability Impact

- `MIGRATED`：Spring AgentOS Gateway。
- `REPLACED`：身份与租户作用域复用既有可信 header filter；运行状态直接来自 Python API。
- `DROPPED`：Spring 侧 progress 状态重建、C4 RuntimeGraph 路由、动态/绑定计数及多前缀兼容。

## Tests（命令与结果）

```powershell
mvn -q '-Dtest=AgentOsGatewayControllerTest,AgentOsGatewayServiceTest' test
```

结果：通过。

```powershell
mvn -q test
```

结果：`134 tests, 0 failures, 0 errors, 0 skipped`，Surefire 累计用时 `35.66s`。

## Known Gaps

- 当前真实 Python v2 API 没有 SSE 资源，因此 Spring 未伪造 SSE 事件流；产品轮询使用 Run/Trace 等真实资源。
- 前端尚未切换到新网关，进入 Phase 9 前旧 UI 会请求已删除的 `/core` 路径。

## Architecture Deviations

计划把 SSE Proxy 列为 Spring 职责，但 wkn 当前 Runtime 与 Phase 7 冻结 API 均未提供 SSE 合同。依据“真实代码优先”，本阶段只实现 HTTP；若后续需要实时推送，应先由 Runtime 事件合同和 ADR 定义，再由 Spring 无状态转发。

## Next Phase

Phase 9：迁移 C4 前端的类型、services、Pinia/derived state 与成果解引用链，并从 Python 应用入口移除旧 `/core` 路由。
