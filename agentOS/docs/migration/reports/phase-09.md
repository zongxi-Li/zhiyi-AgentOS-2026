# Phase 9 — C4 Frontend 数据层迁移

## Phase

Phase 9：把 C4 工作台、Chat 与运行控制台迁移到 AgentOS v2 的引用式产品合同，并关闭旧 Python `/core` 入口。

## Baseline SHA

`a56a9979f84891fe3ae69912ee45eee90f78965e`

## Result SHA

由提交 `10 refactor(frontend): migrate C4 workbench` 固化；确切 SHA 在 Phase 10 报告提交时回填。

## Changed

- 前端唯一 AgentOS 基址改为 `/api/agentos/v2`；Run、Graph、Trace、Provenance、Checkpoint、Review 和 Output 分资源读取。
- Run/Step 类型删除 `input`、`output`、RuntimeGraph、动态补丁、绑定切换计数与旧 planning diagnostics；Execution State 只声明引用、绑定、版本和 checkpoint。
- 工作台、Chat、Console、拓扑、结果、审核与历史改为消费真实 v2 投影；进度只由 Run step 状态派生。
- 成果正文逐个通过 owned `outputRef` 解引用；最终 artifact 从解引用正文的真实 `artifact` 合同生成，不从 Run state 恢复正文。
- 删除动态图计数卡、旧 Runtime timeline、任意 checkpoint resume、Run 删除入口和旧 material API；上传继续复用现有文件文本提取能力，文本随新 Run 输入提交。
- Pack 选择使用应用编译期 UI extension registry；真实 Runtime 没有插件枚举 API，因此不伪造远端 manifest 端点。
- Python 应用入口只构造一套 `WorkflowRuntime`，只挂载 `/ai/agentos/v2`；删除 `agentos_core.py` 和已失去调用方的 C4 material store。
- 删除只验证已移除 `agentos.core`/旧 `/core` API 的测试，保留并更新 wkn 内核、能力纵切、应用、工作台和产品组件测试。

## Capability Impact

- `MIGRATED`：ACG 工作台、拓扑、Trace、Provenance、Review、Deliverables、Run 历史。
- `REPLACED`：前端进度由 v2 Run 的真实 step 状态计算；Pack UI 由已部署应用 registry 提供。
- `DROPPED`：C4 RuntimeGraph DTO、动态/绑定伪计数、Run 正文、旧 `/core` API、任意 checkpoint resume、无 Runtime 合同的删除操作。

## Tests（命令与结果）

```powershell
$env:PYTHONPATH="$PWD\agentOS\src;$PWD\agentOS;$PWD\agent"
python -m pytest agent/tests -q
```

结果：`104 passed, 1 skipped`，4 个既有 warning，用时 `122.07s`。

```powershell
cd frontend
npm test -- --run
```

结果：`24 files passed, 116 tests passed`，用时 `37.03s`。

```powershell
cd frontend
npm run build
```

结果：`vue-tsc` 与 Vite 生产构建通过，`3124 modules transformed`；仅有既有 Sass deprecation 与 chunk-size warning。

生产代码扫描确认：不存在 `/core/workflows`、`/core/plugins`、`/core/materials`、`runtimeGraph`、`dynamicPatch`、`bindingSwitchCount` 或 `agentos.core` 依赖。`DebugTraceCard.step.output` 属于独立 Chat 调试轨迹模型，不是 AgentOS WorkflowStep。

## Known Gaps

- v2 Runtime 当前无 SSE 合同，前端继续轮询 Run，并按需刷新 Graph/Trace 等资源。
- v2 API 当前无 Run 删除和任意 checkpoint resume 合同，对应 UI 操作已移除，而非伪造兼容行为。
- 完整浏览器到容器链路在 Phase 10 随 Docker 健康检查与 smoke test 验证。

## Architecture Deviations

计划允许重写 Pinia store；真实代码中共享 workflow run store 已能存储新 summary，因此保留其结构，只替换 API 与派生字段。计划要求保留交互能力，但 wkn 没有远端插件列表、Run 删除或 checkpoint 任意恢复合同，故这些入口按真实代码删除。

## Next Phase

Phase 10：统一容器 `PYTHONPATH`、完整源码挂载、六个 SQLite 路径和新 volume，并验证五服务 compose 健康与真实 API smoke。
