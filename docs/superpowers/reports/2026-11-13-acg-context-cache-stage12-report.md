# ACG 上下文与缓存优化：阶段一、二

日期：2026-11-13。

## 已实现

### 实际请求诊断

`adapters/request_diagnostics.py` 在 OpenAI Compatible adapter 构造最终请求后，生成各消息段的角色、字符数、Hash、布局版本与共享前缀标识。Schema 已注入，统计针对实际消息而非提示词模板。stream/non-stream 和非法 JSON/传输失败都保留诊断。

诊断通过 StructuredGenerationResult、原生 Agent 和模型事件进入调用 trace。单次最多输出 32 段明细，更多段仅保留数量和总长度。记录不包含正文或密钥；字符数不冒充实际 Token 数。

### 缓存统计

`app/api/model_usage.py` 兼容 DeepSeek 的 `prompt_cache_hit_tokens` 和已有别名。同一用量只采用一个别名，显式 0 不会被其他别名覆盖。

- `/agentos/v2/runs/{run_id}/resource-usage` 新增 cacheGroups，按供应商、模型/版本、布局、共享前缀及能力分组。
- usage 增加 cacheUsageReportedCalls、cacheUsageMissingCalls、cacheMeasuredInputTokens、cacheMissTokens。
- `/agentos/v2/runs/{run_id}/resource-usage/calls` 返回 requestDiagnostics 及模板、Schema、前缀标识。
- 有调用缺少缓存用量时，完整范围的 cacheHitRatio/cacheMissTokens 返回 null；不将未报告伪装成零命中。已报告调用与缺失调用的数量独立可见。

### 首次预读与记忆预算

能力目录增加可选的 `contextPolicy`。没有该字段的插件保留旧行为。

新生成的原生步骤使用 consumer-fields.v1：

1. input.from 继续表示允许消费的字段，prefetch 表示首次预读集合。
2. 能从消费方输入合同确定匹配字段时，预读输入字段和约束/证据/未决项等保护字段；其余授权字段仍保留读取许可。
3. 能力注册者可以用 prefetchFields 按生产能力明确声明预读字段；声明为空或越过生产方合同会拒绝。必需字段和保护字段仍自动保留。
4. 无法确定字段需求时回退完整输入，在 input.contextPolicy.selectionReasons 中记录原因。
5. verification、artifact_generation 默认采用保守回退。没有证明多个交付字段等价之前，继续保留它们的不同正文。该部分属于阶段三。
6. 原生步骤的记忆召回默认预算为 2048 个估算 Token，可在注册能力的 contextPolicy.memoryTokenBudget 中配置；不是完整模型请求总预算。
7. 初始与增量 lowering 使用同一解析函数。增量编译读取保留生产节点的能力和冻结输出合同；保留节点不重新生成策略。
8. 预读字段同时用于 Broker 主路径和无 Broker 的上下文装配路径；后一条路径也校验字段不越过 input.from。相同字段的不同生产来源继续保留在 sourceData 中。

策略、选择理由和结果预读集合进入新 Blueprint 输入合同，由现有执行包的 Blueprint Hash 约束。现有历史执行包不被回写。

## 验证

- AgentOS 模型适配、原生 Agent、公共前缀、上下文投影、初始/增量规划、编译、语义补丁和通信器相关测试：148 passed。
- 新增缓存别名、缺失用量、加权聚合、分组及真实 HTTP 投影测试：11 passed。
- 另行运行三个现有 API 资源用量测试，均在 prepare_run 发生错误：旧测试 fixture 依赖已删除的 WorkflowStep 自动提升路径，未到达统计接口。
- 对照方式：在独立测试进程通过 import loader 加载 HEAD 中本次所有被修改的执行/API 模块，保留工作区文件不变，三个用例仍全部失败。没有修补不相关的旧 fixture。

验证命令：

```text
# apps/agentOS
python -m pytest -q --asyncio-mode=auto tests/adapters/test_execution_prefix.py tests/adapters/test_prompt_context.py tests/adapters/test_openai_runtime.py tests/adapters/test_model_audit_metadata.py tests/adapters/test_model_runtime.py tests/adapters/test_model_runtime_streaming.py tests/adapters/test_native_agent.py tests/runtime/test_semantic_patch.py tests/components/planner/test_context_consumption_policy.py tests/components/planner/test_memory_policy.py tests/components/planner/test_planner_builder_boundary.py tests/components/planner/test_prompt_capability_v2.py tests/components/communicator

# 仓库根目录
python -m pytest -q apps/agent/tests/test_model_cache_usage.py
```

## 生效与边界

后端加载新代码后，新请求开始产生诊断；新编译并激活的执行包获得消费策略。没有启动/重启生产服务，没有重放 `mission_a0bb01491a81`，没有发起收费模型调用，所以不报告命中率提升。

现有公共前缀四段布局保持原实现。大字段内部的章节筛选、多份交付正文归并及完整模型请求总预算尚属阶段三，不能把本次变更描述为已经解决 107,820 Token 的最终汇总问题。

工作区存在并行的工作台/投影改动；本次没有提交或推送，也没有还原这些改动。`agentos_v2.py` 同时含有独立的工作区投影修改，后续如需提交必须按本次功能块区分暂存。
