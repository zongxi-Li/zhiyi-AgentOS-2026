# Phase 1 — wkn 原生基线

## Phase

Phase 1：冻结 `wkn-master@3f6c536` 的真实原生基线，不修改其行为。

## Baseline SHA

`3f6c5365c7ca4358613001ab6529657ba56d36cf`（独立 detached worktree）。

## Result SHA

`3f6c5365c7ca4358613001ab6529657ba56d36cf`（只读验证，无代码变化）。

## Changed

无生产代码变化。冻结的真实事实：

- 物理包为 `agentOS/src/{contracts,components,runtime,adapters,support,tools}` 和 `agentOS/service/agents`。
- `WorkflowRuntime` 构造可注入 Agent/Workflow registry、六类持久化依赖、tool runtime、review/evaluator/task manager、adapter factories、recovery recipe registry、capability catalog、resource directory 和 plugin manifests。
- 应用注入入口为 `set_intent_llm` 与 `set_model_runtime`；tool runtime 由构造器注入。
- 六个存储为 Workflow、Checkpoint、ExecutionValue、Memory、Provenance、Decision。
- 环境变量为 `AGENTOS_WORKFLOW_DB_PATH`、`AGENTOS_LANGGRAPH_CHECKPOINT_DB`、`AGENTOS_EXECUTION_VALUE_DB`、`AGENTOS_EXECUTION_MEMORY_DB`、`AGENTOS_PROVENANCE_DB`、`AGENTOS_AUDIT_DB`。

## Capability Impact

无；该阶段只锁定 wkn 已实现能力与测试现状。

## Tests（命令与结果）

从仓库根目录按计划原样运行（Python 3.14.0 / pytest 8.4.2）：

```powershell
$env:PYTHONPATH="$PWD\agentOS\src;$PWD\agentOS;$PWD"
python -m pytest agentOS/tests -q
```

实际结果：收集 134，`130 passed, 4 failed in 5.29s`。四个失败均是测试用相对路径假定当前目录为 `agentOS/`，分别找不到 `src/runtime/workflow_runtime.py`、`drafts/legacy_execution/MANIFEST.md`、`requirements.txt` 和若干 `src/...` 文件；不是运行时行为失败。环境默认 `python` 指向不含 pytest 的 Hermes venv，测试使用已安装 pytest 的 Python 3.14.0 明确路径执行。

在 `agentOS/` 目录按项目原生目录约定运行：

```powershell
$env:PYTHONPATH="$PWD\src;$PWD;$(Split-Path -Parent $PWD)"
python -m pytest tests -q
```

实际结果：收集 134，`134 passed in 2.84s`（命令墙钟 4.334s）。

导入 smoke：

```python
from runtime import WorkflowRuntime
import contracts
import components
import service.agents
```

结果：通过；模块分别解析到 `agentOS/src/runtime`、`agentOS/src/contracts`、`agentOS/src/components`、`agentOS/service/agents`。

## Known Gaps

- 根目录标准命令存在 4 个 cwd-sensitive 测试失败，Phase 2/3 需将测试改为基于文件位置解析路径。
- `pytest.ini` 仅配置 `pythonpath = src`；只从 `agentOS/` 启动时当前目录隐式补足 `service`，部署环境仍必须显式加入 `agentOS` 根目录。
- 默认 shell 的 `python` 不具备 pytest；这是本机工具链差异，不修改项目依赖来掩盖。

## Architecture Deviations

计划预期标准根目录命令可直接全绿，真实代码为 4 个 cwd-sensitive 测试失败；按“真实代码优先”原样记录，未修改 wkn 基线。

## Next Phase

Phase 2：整体替换 `agentOS/**`；随后单独修复测试/导入基线，不恢复 C4 内核。
