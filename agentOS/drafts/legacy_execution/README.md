# Legacy execution archive

此目录保留旧自研执行器、运行时恢复和两套 checkpoint 的迁移对照版本。它纳入 Git，
但不是 Python package，且不得被生产代码、打包过程或 pytest 收集/导入。

生产替代目标是 `src/components/executor/` 的 AgentOS 融合执行底座，以及
`src/components/recovery/checkpoint.py` 的 SQLite checkpoint 边界。草稿只用于
审阅差异和迁移追溯；后续开发不得在这里继续修复或扩展功能。
