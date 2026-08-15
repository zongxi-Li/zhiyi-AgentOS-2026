# Phase 5 — C4 ACG 能力缺口迁移

## Phase

Phase 5：仅迁移 Capability Matrix 中的内核与应用 P0/P1 `MIGRATE` 缺口，不恢复 C4 RuntimeGraph 或第二套执行器。

## Baseline SHA

`9e0a22d7eaff05361ac8f4fa8c7594bc5d69487d`

## Result SHA

`c4ae5f259782b7def6b288b213576dd25bcaae1a`

## Changed

- 增加引用式 `GraphPatch`/`GraphPatchResult` 合同、图版本和 patch 引用 State 字段。
- 在 `components/executor` 增加不可变 `GraphPatchService`：校验 run/graph/version、DAG、完成节点边界、幂等键和 patch checksum。
- `WorkflowRuntime.apply_graph_patch` 只允许在持久化 `WAITING_REVIEW` 屏障应用补丁；正文进入 `ExecutionValueStore`，State/checkpoint 只保存 ref。
- 修复 review interrupt checkpoint 残留已完成节点 `activeStepIds` 的状态真值问题。
- 增加冻结 scope 内的健康候选查询与一次性 `rebind_step`，切换写入安全 Trace 与 binding history。
- 修复 Agent invocation adapter 按旧 `agentName` 二次解析、绕过冻结 binding 的缺陷；实际调用现在由冻结 `agentId` 决定。
- 在 `components/recovery` 增加无损 contract repair 与 capability-only Recovery Recipe registry；支持稳定匹配和每 run 应用预算。
- Legal contract adapter 改用新 recovery 组件，不再抛出迁移占位错误。
- Legal 检索和证据匹配节点使用受审计 `MemoryType.EVIDENCE` 策略。
- 保留应用层 Tavily/知识库只读工具链并补齐 wkn wiring 回归：授权、离线拒绝、安全事件与 citation 输出。

## Capability Impact

- `MIGRATED`：graph version、动态安全图修改、GraphPatch、alternate binding、contract repair、Recovery Recipe、真实联网检索链、Legal evidence memory。
- `REPLACED`：checkpoint CAS、冻结 scope、健康过滤、工具授权、引用所有权继续使用 wkn 实现。
- `DEFERRED`：自动外部调用重试/限流、commitId 外部传播、孤儿 GC、五阶段 fault injection、BLACKBOARD、DEBATE，仍属于 Phase 11。
- `DROPPED`：无新增；未恢复任何 C4 RuntimeGraph/Executor/旧数据合同。

## Tests（命令与结果）

```powershell
$env:PYTHONPATH="$PWD\agentOS\src;$PWD\agentOS;$PWD\agent"
python -m pytest agentOS/tests agent/tests/test_wkn_application_wiring.py agent/tests/test_legal_wkn_vertical_slice.py agent/tests/test_wkn_network_tool_chain.py -q
```

结果：`148 passed, 3 warnings in 7.26s`。

新增断言覆盖：

- stale graph version 冲突、patch 幂等 replay、DAG/完成边界校验；
- patch 正文独立存储、State 仅留 `graphPatchRef`、新 checkpoint 与恢复后新拓扑执行；
- pending step 一次性备用绑定、预算耗尽拒绝、真正调用新 agentId；
- contract repair 只做无歧义数组包裹与 schema 默认值，不补造必填语义；
- recipe 稳定匹配、返回副本、应用预算耗尽拒绝；
- 联网 fixture 引用、工具事件不含 query、离线/未授权调用不触达 delegate；
- Legal evidence memory 类型、引用归属和 State 正文隔离。

## Known Gaps

- Recovery Recipe 当前是声明式选择合同；具体 node template 仍通过已审计 `GraphPatch` API 在安全屏障实例化，不在失败中的未持久化图上原地变异。
- 生产 Tavily 调用需要部署环境提供 `TAVILY_API_KEY`；测试使用确定性 provider fixture，未消耗真实外网额度。
- 三条 warning 来自既有 Pydantic 配置、Chroma telemetry 和 Legal RAG fallback 中未等待 embedding coroutine，不影响本阶段断言，后续应独立清理。
- C4 旧测试中依赖 `run.output.artifacts`/RuntimeGraph 的测试尚未删除或伪兼容；Phase 7 将按新 API 合同替换。

## Architecture Deviations

C4 可在失败处理过程中直接修改可变 RuntimeGraph。wkn 的真实实现以不可变 Blueprint、稳定 commit 和 checkpoint CAS 为核心，因此本阶段把动态修改收束到持久化审核屏障，并生成新图 revision；这保留动态图/恢复能力，同时不破坏引用式 State 与确定性恢复。

## Next Phase

Phase 6：按 General/Native → Programmer → Education → Writer 的固定顺序验证并迁移领域 Pack；每个 Pack 独立完成 profile、capability、workflow、model/tool、memory policy、output contract 和集成测试。
