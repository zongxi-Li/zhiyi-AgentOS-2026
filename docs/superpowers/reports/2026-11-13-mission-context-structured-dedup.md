# Mission 上下文结构化去重

## 问题和改动

`mission_c923b0618aa1` 的 `run_9569b3ebcc3b` 在两个核查节点接收了大份交付内容。工作区原有请求投影已经合并完全相同的长字符串，但 `artifact.structuredData` 与 `deliverable` 中重复的对象、列表和较短字段仍有重复结构开销。

本次扩展 `adapters/model/prompt_context.py` 的现有投影，在请求内共享完全相同的 JSON 对象和数组。引用使用 `inline-content.v2`，按依赖顺序列出；先恢复目标内部的引用，再复制整个目标。v1 字符串引用继续受支持。比较新旧投影的完整规范 JSON 长度，采用较短者，避免新增引用开销抵消收益。

运行时提示合同说明 v2 的类型及恢复顺序，renderer 版本升级至 v6。仅处理数据内容通道，保留每个使用位置的来源和信任标签。数组顺序、空值、布尔值、整数、浮点数及不同生产者的内容均保留。任务原始材料使用两种策略一致的处理方式，避免按节点选择投影策略时改变共享材料前缀。

本次没有变更冻结的通信字段权限、输入输出合同、历史产物、来源账本或统计。复核仍取得完整的授权内容，没有引入仅看差异的验收策略。

## 离线对照

使用本地持久化的 18 份 ContextPack，只读比较工作区原有字符串投影与本次结构化投影。比较范围是存储的上游内容及其来源/引用信封；任务材料置为空，不包含完整模型提示、Schema、工具定义、记忆或工具结果。因此这些是规范 JSON 字符数，不是供应商 Token 或费用。

| 节点 | 原有投影字符数 | 新投影字符数 | 减少 |
| --- | ---: | ---: | ---: |
| native_general_agent_14 | 63,678 | 53,921 | 15.32% |
| native_general_agent_16 | 75,893 | 65,972 | 13.07% |
| 全部 18 份上下文 | 332,250 | 312,572 | 5.92% |

全部 18 份投影均通过按引用顺序还原后的规范 JSON 完全一致检查，其他 16 份没有增大。

可复现命令（数据库路径按本地环境指定）：

```powershell
python ops/scripts/audit_context_projection.py --value-db "$env:LOCALAPPDATA/ZhiyiNative/default-clean-20261106/data/values.sqlite3" --run-id run_9569b3ebcc3b
```

该脚本以 SQLite `mode=ro` 读取，不输出正文，不调用模型，也不修改历史记录。

## 验证与生效

在 `apps/agentOS` 执行：

```text
python -m pytest -q tests/adapters/test_inline_content.py tests/adapters/test_prompt_context.py tests/adapters/test_execution_prefix.py tests/adapters/test_native_agent.py tests/adapters/test_openai_runtime.py tests/adapters/test_native_prompt_v2.py tests/adapters/test_prompt_runtime_pr02.py tests/adapters/test_prompt_runtime_pr03.py tests/adapters/test_request_budget.py
```

最终结果：118 passed。覆盖结构化还原、类型区分、数组次序、来源伪造引用保留为普通数据、共享材料前缀、无增大回退、模型请求构建、续写、信任边界及预算相关测试。

本次仅完成代码与离线验证，没有重启本地服务或发起收费模型重放。后端加载新代码后，后续原生能力请求使用新投影；已完成 Run 的通信统计不会被追溯改写。模型能否正确利用引用、实际输入 Token 和交付质量仍需新 Run 的端到端对照确认。
