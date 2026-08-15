# ADR-001：引用优先的 AgentOS Application API

状态：Accepted  
日期：2026-08-15

## 决策

新 API 固定使用 `/ai/agentos/v2`。Python `WorkflowRuntime` 是 Task、Run、Graph、Review、Checkpoint 与恢复状态的唯一真源；HTTP 只做鉴权后的投影。

`GET /runs/{runId}` 只返回生命周期、步骤安全状态、摘要及 `outputRefs/contextRefs/memoryRefs/traceRefs/provenanceRefs/graphPatchRefs`。它不返回 task input、ContextPack、模型响应、工具参数、step output 或最终成果正文。

成果正文只能通过：

```text
GET /ai/agentos/v2/runs/{runId}/outputs/{outputRef}
```

读取。服务必须先确认调用者可访问 run，并确认 `outputRef` 属于该 run 的 execution state，再调用 `ExecutionValueStore` 解引用。

Graph、Trace、Provenance、Checkpoint 与 Review 使用独立子资源：

```text
/runs/{runId}/graph
/runs/{runId}/trace
/runs/{runId}/provenance
/runs/{runId}/checkpoints
/runs/{runId}/reviews
```

Graph 来自持久化 `ACGBlueprint` 与引用式执行状态，不构造 C4 RuntimeGraph。不存在的数据不填充零值计数或伪造事件。

## 安全边界

- Run 与所有子资源复用相同 user/tenant ownership 检查；无权访问统一返回 404。
- Output API 不接受未出现在该 run `outputRefs` 中的引用。
- Trace 投影递归删除 token、secret、prompt、arguments、response、content 和 input 等敏感正文键。
- 错误响应只使用稳定的 404/409/422 摘要，不回传底层异常、prompt、模型响应、工具参数或正文。
- 分页参数固定为 `page` 和 `pageSize`，单页最大 100。

## 兼容策略

本 API 不承诺兼容 C4 `/core` DTO。旧路由只在 Spring 与前端迁移期间存在，并将在 Phase 9 后删除；不得为旧 UI 恢复 `step.output`、`runtimeGraph`、`dynamicPatch` 或 binding counter。

## 结果

客户端必须显式获取成果正文，因而可以在 Gateway 和前端层分别执行授权、缓存和展示策略。Run/checkpoint 保持轻量且可安全轮询，Runtime 的引用归属验证成为唯一解引用边界。
