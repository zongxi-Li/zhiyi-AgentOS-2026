# Planner Runtime Streaming 实施与验收记录

## 结论

Planner Runtime Streaming 的代码实现已完成，自动化契约和前端构建均通过；生产签收仍保持 **NOT YET COMPLETED**，原因是本轮没有连接真实 Provider 做端到端 Workbench 验证，且全量后端仍暴露两个与本次功能无关的现有失败。

## 已实现边界

- Planner 的 intent profile、decompose、outline、detail、relations 及各类 repair 调用统一走 Runtime-owned `stream_generate_json`。
- 每次规划共享 `AGENTOS_LLM_PLANNING_TOTAL_TIMEOUT_SECONDS` 总预算（默认 660 秒）；每个 provider stream 按剩余预算执行 TTFT、idle 和 total deadline。
- `callKey` 稳定区分 `intent_profile`、`intent_profile.repair1`、`outline`、`detail:N`、`relations`、`relations.repair`、`repair_coverage` 等逻辑调用。
- JSON 片段只在模型运行时内部缓冲；Planner Broker/SSE/Trace 只输出 lifecycle、stage、计时、chunk/length 和语义计数，不输出 prompt、raw JSON、reasoning 或 credentials。
- Planner 事件为 run-scoped，`nodeId`/`attemptId` 保持 `null`；Node streaming 继续沿用同一 Broker、同一 SSE endpoint 和同一前端 runtime store。
- Planner 取消/异常路径关闭 provider async iterator；跨线程规划事件通过 owner loop 投递，不为每个事件创建临时 asyncio loop。
- RunProgressEditor 显示真实 planning stage、model phase、TTFT、Idle、elapsed、CallKey，以及 profile/plan/graph 计数；不会用假计时器强制跳图。
- `/runs/{run_id}/events` 在建立长连接前执行 Run 访问校验，并禁用代理缓冲。

## 验证证据

- Planner/Broker/timeout 定向后端回归：18 passed。
- Python compileall：passed。
- 前端 Vitest：57 files / 301 tests passed。
- 前端生产构建 `npm run build:web`：passed；仅保留既有 large-chunk warnings。
- `git diff --check`：passed（Git 输出的 LF→CRLF 提示不是 whitespace error）。
- Fake provider → Native Agent → Broker → SSE envelope：passed；completion payload redaction、disconnect cleanup、slow-consumer lifecycle retention 均有覆盖。

## 全量回归遗留项

后端全量回归结果：413 passed、2 failed、54 warnings。

1. `test_projection_replay_repairs_partial_blueprint_registration`：当前实现将 `run.prepared` 保存在 Execution Runtime outbox，测试仍从 Identity projection queue 查找该事件，失败为现有事件归属假设不一致。
2. `test_long_run_refreshes_local_agent_heartbeat_before_later_step`：10ms heartbeat TTL 下出现一次 1 秒超时；随后单独重跑通过，归类为非确定性调度抖动。

两项均未修改为掩盖本次 Planner streaming 结果；需要后续单独修复或稳定化。

## 尚未验证

尚未使用真实 GLM/DeepSeek/OpenAI-compatible Provider 完成一次新的 ACG Run，并在真实浏览器中核对 SSE 到 RunProgressEditor 的全链路。因此 Provider stream payload 兼容性、真实 TTFT/Idle 展示和取消时底层 HTTP 连接的实测结果仍待人工验收。
