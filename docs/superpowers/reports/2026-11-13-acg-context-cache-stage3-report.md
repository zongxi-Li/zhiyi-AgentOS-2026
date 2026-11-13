# ACG 上下文与缓存优化：阶段三本批实施

日期：2026-11-13。

## 实现与边界

### 重复内容无损投影

扩展 `adapters/model/prompt_context.py`，在已有 data/sourceData 镜像去重之后，复用完全相同的长字符串，以及相同的 JSON 对象和数组。结构化复用采用工作区同期出现的扩展，保留并按最终代码统一验证。

- `inline-content.v1` 复用长字符串；`inline-content.v2` 允许复用结构化交付内容。每个被替换位置保留 null 和原有键/数组下标，由运行时单独生成的引用表明确标识。
- 引用只指向本请求中已有的内容，按照依赖顺序恢复；不同来源记录、不同正文、数据类型、顺序、否定约束和普通 null 均保留。
- 来源正文里伪造的引用表仍是数据。投影不改写存储、输出合同、通信账本或工具权限。
- 在字符串投影与结构化投影之间选较小表示；短内容或引用开销更大时保留原内容。
- 任务材料先于节点来源处理，结构化策略选择不改变共享任务段。共享段拆分后先还原 taskSources，再解析投影引用。
- 请求协议升级为 execution-request.v3，渲染器升级为 prompt-runtime-renderer.v5，系统合同解释引用和信任边界。版本变化后的真实缓存复用需重新测量。

当前原生 artifact_generation 已只让模型生成 deliverable/verification，再确定性生成 final_answer、artifact 等展示表示；本批保留该输出和 UI 合同，仅压缩下游模型的输入表示。

### 完整请求的可配置估算预算

新增 `contracts/request_budget.py` 的 request-budget.v1，由能力目录 `contextPolicy.requestBudget` 声明，经初始和增量 lowering 进入冻结 inputSpec。NativeGeneralAgent 和工具会话使用该冻结值。

```json
{"version":"request-budget.v1","totalTokens":32000,"outputReserveTokens":8000}
```

数值仅为配置示例。原生目录默认 requestBudget 为 null，本批没有为所有节点设置统一硬限，也不改写历史包。

OpenAI Compatible adapter 在 Schema 注入后的真实发送边界，对 messages、tools/functions、response_format 统一估算；系统提示、公共任务、节点输入、记忆、工具结果/参数以及续写均包含在内。沿用项目的 JSON 字符数 / 3.2 估算法，诊断显式标注 estimator，不视为供应商精确 Token 数。

配置预算时，估算输入加输出预留超限会在联网前抛出 MODEL_INPUT_BUDGET_EXCEEDED，保留无正文诊断。预算是内部合同，不作为供应商 option 外发，也不新增 max_tokens 限制。输出预留是预算检查的预留量，并非供应商实际输出 Token 的硬上限。

工具每轮调用都检查预算；某轮工具结果过大时不会继续发送。已经执行工具后发生容量错误，不通过换分片标识重跑工具。现有工具 WAL 和恢复权限继续拥有执行权威。

### 现有 Workset 修复

- 已声明的材料 Workset 遇到输入估算预算超限，可进入现有确定性二分，再归并结果；不可继续细分时保留错误，不截断内容。
- 子范围使用原片段内的 Unicode 码点绝对偏移；修复多层二分局部偏移不准确的问题。
- Map 和递归 Reduce 标识包含完整片段范围，修复同层左右子片段/归并使用相同标识的冲突。
- 每个新 Map 结果持久化 `_worksetCoverage`，记录原 Manifest、Fragment、校验摘要和完整处理范围。
- 未处理完所有声明片段不允许 seal；恢复时检查结果数量不超过声明范围。原有无覆盖附加信息的结果仍可读取。
- 覆盖记录证明片段执行范围，不单凭数量宣称模型完成了所有业务验收项。

本批没有自动把最终汇总、评审、验收节点的上游交付物注册成新材料，没有改动 DAG 或绕过 Planning Commit。自动按章节/检查项规划、授权并激活 Workset 仍是阶段三剩余工作。

## 历史 Run 只读对照

Mission：mission_a0bb01491a81；Run：run_4157e2ae795b。以阶段二已有顶层镜像投影为基准，对比当前最终无损投影。

| 范围 | 投影前字符数 | 投影后字符数 | 减少字符数 |
| --- | ---: | ---: | ---: |
| 27 个上下文包合计 | 730,261 | 574,552 | 155,709（21.32%） |
| 最终汇总 native_general_agent_25 | 190,686 | 117,343 | 73,343 |
| 架构评审 native_general_agent_9 | 98,960 | 53,225 | 45,735 |
| 最终验收 native_general_agent_26 | 80,614 | 43,983 | 36,631 |

27 个投影均逐条展开引用并与原对象比较，通过无损还原。统计范围只有持久化上下文的上游内容，不包含完整请求的系统段、Schema、记忆、工具会话或输出；不得将 21.32% 解释为整个模型输入 Token 减少率或缓存命中率提升。

最初字符串版本测得减少 115,100 字符（15.76%）；上表已按包含结构化复用的最终代码重新计算。

可复现命令（仓库根目录，数据库只读，不调用模型）：

```powershell
python scripts/audit_acg_context_projection.py --data-dir C:/Users/LZX/AppData/Local/ZhiyiNative/default-clean-20261106/data --run-id run_4157e2ae795b
```

另有工作区同期新增的 `ops/scripts/audit_context_projection.py`，比较字符串版与结构化版的增量，基准不同，不混用其百分比。

## 验证

- AgentOS 请求投影、预算、工具会话/流式、Workset、模型适配、原生 Agent、语义补丁、规划编译、通信器、Content Manifest 和附件测试：240 passed。
- Agent API 缓存统计及 HTTP 投影回归：11 passed。
- 本批共 251 项通过；仅出现既有 Pydantic/PyPDF2 弃用提示。没有把这一结果描述为全仓库测试通过。
- 增加多层分片绝对范围、Map/Reduce 提交标识唯一性、恢复覆盖、工具执行后禁止重复拆分、Schema/续写/工具参数及结果参与预算的验证。

AgentOS 验证命令：

```text
python -m pytest -q --asyncio-mode=auto tests/adapters/test_inline_content.py tests/adapters/test_request_budget.py tests/adapters/test_workset_coverage.py tests/adapters/test_execution_prefix.py tests/adapters/test_prompt_context.py tests/adapters/test_openai_runtime.py tests/adapters/test_model_audit_metadata.py tests/adapters/test_model_runtime.py tests/adapters/test_model_runtime_streaming.py tests/adapters/test_native_agent.py tests/adapters/test_unified_tools.py tests/adapters/test_tool_turn_streaming.py tests/runtime/test_semantic_patch.py tests/components/planner/test_context_consumption_policy.py tests/components/planner/test_memory_policy.py tests/components/planner/test_planner_builder_boundary.py tests/components/planner/test_prompt_capability_v2.py tests/components/communicator tests/components/content tests/components/attachments
```

API 验证在仓库根目录运行 `python -m pytest -q apps/agent/tests/test_model_cache_usage.py`。

## 生效与剩余工作

后端加载代码后，原生请求使用新的投影协议；预算仅对声明并冻结了 requestBudget 的执行包生效。没有重启服务、修改生产数据库、重放任务或发起外部模型调用，没有新增真实命中率或模型交付质量验收结果。

整个阶段三仍未完成：下一步需在现有规划/激活权威下，把大汇聚任务编译为按章节或检查项覆盖的 Workset，并处理 Reduce 输入仍然超限的规划反馈。阶段四继续由实际请求和供应商用量证据触发。

工作区含并行的工作台、审批和工具流式改动；本批未提交、推送或还原这些工作。后续提交需按实际功能块区分共享文件中的改动。
