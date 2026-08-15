# Legacy execution manifest

| 原路径 | 归档原因 | 生产替代目标 | 当前状态 |
| --- | --- | --- | --- |
| `src/components/executor/` | 自研调度、运行图和适配器已被 LangGraph 融合底座替代 | `src/components/executor/ACGExecutionGraph`、`ACGGraphCompiler` | 新 ACG Blueprint 已接管执行，禁止生产导入 |
| `src/components/recovery/runtime_recovery/` | 自研 RuntimeGraph 恢复、补丁和控制器不再是运行时权威 | `ACGCheckpointStore`、`ExecutionInterrupt`、`ExecutionResumeCommand` | 新 ACG Blueprint 已接管恢复，禁止生产导入 |
| `src/components/auditor/governance/checkpoint.py` | 旧 run 内嵌 checkpoint 与 RuntimeGraph 绑定 | `src/components/recovery/checkpoint.py` | 已归档，禁止生产导入 |
| `src/components/recovery/checkpoint.py` | 旧进程内字典 checkpoint 不支持进程重启 | `ACGCheckpointStore` SQLite | 已归档，禁止生产导入 |

禁止生产导入：`src/` 内不得出现 `drafts.legacy_execution` 或旧路径的 import。
`pytest.ini` 的 `testpaths = tests` 保证默认 pytest 不收集本草稿目录。

历史 `runtimeGraph` 仅保留只读兼容展示，不可作为新执行或恢复状态来源；遇到该历史载荷时
Runtime 返回 `ACG_EXECUTION_ENGINE_MIGRATING`，要求创建新的 ACG Blueprint 运行版本。
