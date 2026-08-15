# Phase 3 — Python Application Adapter 迁移

## Phase

Phase 3：由 Application 完整装配唯一 wkn WorkflowRuntime，并移除生产代码对 `agentos.*` 的依赖。

## Baseline SHA

`9b87219eae92d0105b9bbddd40938c3073d54061`。

## Result SHA

`1ca2afee8863a989ae4631aa30a5990f01559a25`

## Changed

- 新增 `app.execution.wiring` 作为 composition root，显式构造 Agent/Workflow registry 和 Workflow、Checkpoint、ExecutionValue、Memory、Provenance、Decision 六个存储。
- 由应用注入 intent LLM、structured model runtime、read-only tool runtime、native runtime 与四个 Pack。
- 将后台 asyncio 任务所有权迁到 `app.execution.coordinator`；它只调用 WorkflowRuntime，不保存业务状态。
- 为应用拥有的 SQLite 连接、模型线程池和单实例文件锁增加 shutdown 释放路径。
- 将 app 与 Pack 的生产导入机械迁到 `runtime/contracts/components/adapters/support/service` 真实模块。
- 删除会遮蔽真实模块的 `agent/agentos.py` 兼容入口。
- C4 contract repair agent 暂时显式报告 `CONTRACT_REPAIR_MIGRATION_PENDING`，不通过兼容代码伪装完成。

## Capability Impact

- `MIGRATED`：Python Runtime wiring、外部模型/工具注入、应用后台调度、存储生命周期。
- `MIGRATE`：contract repair、code index builder 和旧 API DTO 仍为显式缺口。
- `REPLACED`：Pack 的公共 Agent/Skill/Workflow/Planning 类型改用 wkn 边界。

## Tests（命令与结果）

```powershell
python -m compileall -q agent/app agent/packs
python -m pytest agent/tests/test_wkn_application_wiring.py agentOS/tests -q
```

结果：compileall 通过；`136 passed, 1 warning in 4.87s`（134 个 kernel tests + 2 个 application wiring tests）。

应用 import smoke 使用六个独立临时数据库并导入 `app.main`，结果 `APP_IMPORT_OK`，Runtime 类型为 `runtime.workflow_runtime.WorkflowRuntime`。Windows GBK 控制台对既有 emoji 日志产生非致命 logging error，不影响 import。

生产导入门禁：

```powershell
rg -n 'agentos\.core|from agentos|import agentos' agent/app agent/packs -g '*.py'
```

结果：0 条。

全量旧 application tests 的 collect-only 结果：109 个可收集，28 个 collection error；错误均来自尚未迁移的 C4 测试自身仍导入 `agentos.*`。这些测试会在对应 capability/pack/API 阶段改写，未添加兼容包使其假绿。

## Known Gaps

- C4 API 文件虽然已使用 wkn 类型，但仍投影 legacy RuntimeGraph/正文等旧语义；Phase 7 前不视为冻结 API。
- contract repair、动态图、alternate binding 与 code index 仍待 Phase 5。
- C4 tests 需要按能力逐批转为 wkn 合同；当前不以旧测试全绿作为 Phase 3 验收。
- `app.main` 导入仍触发若干旧创新模块的重型初始化，属于后续产品清理。

## Architecture Deviations

计划示意中的 tool registry 注入被真实代码实现为 `AgentsToolRuntime` 实例注入；没有另造 registry 类型。wkn 自带的进程级 adapter factory 仅供旧 Skill 边界使用，WorkflowRuntime 使用显式实例。

## Next Phase

Phase 4：Legal Contract Review 黄金纵切，验证 committed replay、引用式 checkpoint、审核重启和条件 skip。
