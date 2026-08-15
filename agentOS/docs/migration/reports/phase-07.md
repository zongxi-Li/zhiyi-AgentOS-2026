# Phase 7 — 冻结新的 Application API

## Phase

Phase 7：以真实 `WorkflowRuntime` 为唯一真源，冻结引用优先的 Application API。

## Baseline SHA

`8ffb9c6148860e3d4a6dc3dfa8aa9c07750666dc`

## Result SHA

由提交 `08 feat(api): establish AgentOS application API` 固化；确切 SHA 在 Phase 8 报告提交时回填。

## Changed

- 新增 `/ai/agentos/v2` API，资源边界为 Run、Graph、Output、Trace、Provenance、Checkpoint 与 Review。
- Run 投影仅包含生命周期、安全摘要和引用；task input、ContextPack、模型/工具正文与 step output 均不进入状态响应。
- Output API 在解引用前同时验证 run 访问权和 `outputRef` 对该 run 的归属。
- Trace 响应递归脱敏 prompt、arguments、response、content、input、token、secret 等正文键。
- 创建接口支持调用者域内的 `clientRequestId` 幂等语义，指纹冲突稳定返回 409。
- 新增 ADR-001，冻结 URL、分页、授权、错误边界，并明确不兼容 C4 `/core` DTO。

## Capability Impact

- `MIGRATED`：HTTP Application API。
- `REPLACED`：任务、运行、审核、checkpoint 与恢复状态全部直接投影 wkn Runtime，不在 API 重建状态机。
- `DROPPED`：新 API 中的 C4 RuntimeGraph、`step.output`、动态补丁正文和伪造计数。

## Tests（命令与结果）

```powershell
$env:PYTHONPATH="$PWD\agentOS\src;$PWD\agentOS;$PWD\agent"
python -m pytest agent/tests/test_agentos_v2_api.py -q
```

结果：`3 passed, 1 warning in 3.25s`。

```powershell
python -m pytest agentOS/tests agent/tests/test_wkn_application_wiring.py agent/tests/test_legal_wkn_vertical_slice.py agent/tests/test_wkn_network_tool_chain.py agent/tests/test_wkn_domain_packs.py agent/tests/test_agentos_v2_api.py -q
```

结果：`155 passed, 3 warnings in 9.80s`。

## Known Gaps

- 旧 `/ai/agentos/core` 路由在 Spring 与前端迁移完成前仍暂时挂载；Phase 9 必须移除，不作为兼容承诺。
- 当前 API 使用页码分页；若真实数据规模证明需要 cursor，应另立 ADR，不在迁移中预先扩展。
- 现有 Pydantic、Chroma 与 RAG warning 未混入本阶段清理。

## Architecture Deviations

计划未冻结 HTTP 前缀；真实应用已有 `/ai` 路由根，因此选择 `/ai/agentos/v2`，Spring 将只代理该合同。API 没有新增 DTO 状态存储，也没有把输出正文复制回 Runtime state。

## Next Phase

Phase 8：把 Spring 改成 `/api/agentos/v2` 的鉴权、scope、DTO 校验、HTTP/SSE 代理和错误映射层，删除其旧 RuntimeGraph 投影。
