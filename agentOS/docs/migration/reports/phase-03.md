# Phase 3a — wkn 测试与导入基线修复

## Phase

提交边界 03：恢复 wkn kernel test/import baseline；这是应用迁移前的独立前置步骤。

## Baseline SHA

`c81f8babc55e6518d6ae306187fcb5ccc77a6a1a`。

## Result SHA

由提交 `03 fix(agentos): restore wkn test/import baseline` 固化；确切 SHA 在下一阶段报告提交时回填。

## Changed

- 将源码边界测试中的文件查找改为相对测试文件定位 `agentOS/` 根目录，不再依赖进程 cwd。
- 将 `pytest.ini` 的 Python path 从仅 `src` 改为 `. src`，显式支持真实的 `agentOS/service/agents` 物理目录。
- 未改变 WorkflowRuntime 或任何组件行为。

## Capability Impact

无能力增删；只恢复 `REPLACED` 内核的可重复验证入口。

## Tests（命令与结果）

```powershell
$env:PYTHONPATH="$PWD\agentOS\src;$PWD\agentOS;$PWD"
python -m pytest agentOS/tests -q
```

结果：收集 134，`134 passed in 4.05s`（命令墙钟 5.637s）。

## Known Gaps

应用生产代码仍依赖 `agentos.core.*`，尚未进入可启动状态。

## Architecture Deviations

无内核行为偏差。只修复 wkn 测试对启动目录的隐式假设。

## Next Phase

Phase 3：迁移 Python Application wiring，构造并注入唯一 WorkflowRuntime。
