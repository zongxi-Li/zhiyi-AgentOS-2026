# Prompt Runtime 提示词权威与审计改造实施记录

> 日期：2026-09-18  
> 范围：Planner、Native Executor、Verifier、Synthesizer 的提示词权威、上下文信任、可审计身份、Provider 兼容与行为评测。  
> 状态：**工程实现已完成，整体为部分收敛（partially converged）**。确定性测试与回归测试已覆盖；尚未执行配置真实模型后的行为评测，不能标记为 `Prompt Runtime Converged`。

## 1. 背景与目标

改造前，Planner 和 Native Executor 的行为指令、任务合同、来源材料、记忆、上游输出与工具观察会被拼接进普通用户提示词。虽然模型运行时已经支持消息数组，但结构化生成路径通常只发送单条 `user` 消息；Native 路径中的 `systemBoundary` 也只是用户 JSON 中的一个字段，不具备真正的系统级权威。

本轮改造的目标是建立单一、可追溯的提示词运行时边界：

1. 将静态 AgentOS 行为规范与运行时数据分离，静态规范经由真实 `system` 消息传递。
2. 对来源、记忆、上游结果、证据与工具观察明确标记信任等级，避免数据被当作指令执行。
3. 为能力、验证和产物合成提供不同的系统策略，不改变运行时对工具、拓扑、调度和持久化的权威。
4. 对一次调用提供稳定模板、实例、Schema 与系统前缀身份，同时不存储原始提示词或敏感上下文。
5. 覆盖通用 OpenAI 兼容传输与 GLM/Zhipu 的结构化输出差异，并提供真实模型行为评测入口。

以下内容不在本轮范围内：重写 `TaskPlanTopologyCompiler`、`RuntimeGraph`、调度器、Checkpoint、工具运行时、ACG 构建、能力绑定或 Artifact 持久化；模型只能生成受现有 Schema、校验器和运行时合同约束的输出。

## 2. 最终架构

```text
Prompt Runtime
  Kernel + Agent Preset + Capability Policy + Runtime Contract
  -> 一个稳定的 system 消息

动态请求数据
  PlanningRequest / ExecutionRequest + response schema
  -> user 消息

RegisteredModelRuntime
  -> 最终 provider-facing 调用身份
  -> StructuredGenerationResult 审计记录

既有审计投影
  Planner promptAudit / Native modelInvocations / Run Trace
```

权威边界保持如下：

| 层级 | 负责内容 | 不能负责内容 |
| --- | --- | --- |
| Prompt Runtime | Kernel、Preset、能力策略、信任封装、稳定系统前缀 | 调度、拓扑变更、工具授权、持久化 |
| Model Runtime | 消息传输、Provider 适配、最终调用身份、结果审计 | 选择 Agent 策略或定义能力语义 |
| ACG/Runtime 控制面 | 任务身份、能力绑定、工具允许集、输出合同、Schema 校验 | 将不可信来源升级为系统权威 |
| Provider Adapter | 传输兼容与结构化输出模式 | Kernel、Preset、Capability Policy 的选择 |

系统消息的稳定组合顺序为：`Kernel -> Preset -> Capability Policy -> Runtime Contract`。每个模型调用只产生一个上游合成的 `system` 消息，动态任务与上下文始终进入 `user` 请求。

## 3. 分阶段实施

### PR-0 / PR-1：Planner 系统权威与来源封装

PR-0 扩展既有结构化生成接口，使 `system_prompt` 成为可选参数，并沿同步、流式、受保护运行时和 Provider Adapter 透传。该参数保持可选，因此未迁移的调用方行为不变。

PR-1 在 Planner 公共调用边界 `call_planning_model` 注入静态 Kernel 与 Planner Preset，覆盖意图分析、分解、分阶段规划以及各类修复调用。PlanningRequest 的来源字段以信任标签序列化；任务分解移除了按复杂度设定近似节点数的目标，改为要求最小充分计划。

该阶段同时修正 Provider 消息顺序：通用 OpenAI 兼容路径保留原消息；GLM/Zhipu 在已有 AgentOS 系统前缀后追加仅用于传输的 Schema 兼容合同，不再抢占系统消息首位。

### PR-2：Native 执行链路迁移

PR-2 将 Native 模型调用改为结构化 `ExecutionRequest` 加受信任系统内容，淘汰 `systemBoundary` 与通用 Artifact 覆盖指令。迁移覆盖同步、流式、JSON/合同修复、容量恢复、部分归约、Artifact 分段生成、汇总与内部验证。

上下文按以下类别进入用户请求：

| 信任类别 | 典型来源 | 使用边界 |
| --- | --- | --- |
| `runtime_authoritative` | 任务身份、已编译合同、能力绑定、允许工具与输出要求 | 运行时控制事实，不接受任务携带材料冒充 |
| `verified_evidence` | 已验证证据引用 | 作为证据，不转换为行为指令 |
| `agent_generated` | 上游 Agent 输出、记忆 | 仅为待判断数据，不能自动升级为证据 |
| `external_untrusted` | 来源材料、附件、插件负载、用户/外部数据 | 仅作为数据，不能修改系统策略 |

工具观察额外带有认证来源元数据，但内容权威仍是数据而不是指令。`information_retrieval` 保持为运行时授权的确定性工具路径，其余原生能力经统一模型入口调用。

本阶段复用既有版本化 `CapabilityPromptProfile`，未创建第二套能力策略模型。`verification` 使用 Verifier Preset，只评估候选结果而不得改写；`artifact_generation` 使用 Synthesizer Preset，遵循 Artifact 合同并保留不确定性与溯源。

### PR-3：调用身份、审计投影与行为评测

PR-3 建立 UTF-8 规范 JSON、对象键排序、数组保序的哈希语义，并拒绝非有限 JSON 值：

| 字段 | 标识对象 | 排除内容 |
| --- | --- | --- |
| `promptTemplateHash` | 静态 Kernel、Preset、能力策略、受信任协议与版本元数据 | mission、来源、记忆、run id、时间戳 |
| `stablePrefixHash` | 单一合成的系统消息 | 动态用户请求 |
| `schemaHash` | 规范化响应 Schema | 消息和 Provider 细节 |
| `promptInstanceHash` | 有序规范消息、Schema、有效 Provider/模型/版本、结构化输出模式与行为选项 | request id、trace id、超时、重试次数、流式传输模式 |

审计通过既有 `StructuredGenerationResult.audit_record()`、Planner `promptAudit`、Native `modelInvocations`、流式 `model.started/model.completed` 与成功 Run Trace 投影传递。记录仅保存哈希、受限版本/标识、Provider/模型元数据和信任类别计数；绝不保存 system/user 原文、来源、记忆、附件、插件、工具观察或生成内容。

同步与流式 Provider 失败对象在请求规范化后会带上安全身份字段。受保护的 RuntimeGraph 失败事件投影尚未完整携带这些新增字段，后续应以独立 Runtime/Trace 变更补齐，避免扩大本轮 Prompt Runtime 的控制面范围。

## 4. 能力策略摘要

所有能力继续使用现有 catalog `outputContract`。工具声明仅表示需求或偏好，实际可用性仍由运行时允许集决定。

| 能力组 | 共同原则 | 代表能力 |
| --- | --- | --- |
| 理解与分析 | 明确任务边界、事实与假设、来源和缺口 | `task_understanding`、`requirement_analysis`、`analysis`、`comparative_analysis` |
| 证据与提取 | 可追溯映射、保留冲突，不把来源存在等同于结论成立 | `information_extraction`、`evidence_analysis`、`information_retrieval` |
| 设计与规划 | 明确输入/输出/责任/依赖/单位与约束，未获支持的选择标为假设 | `process_decomposition`、`resource_planning`、`architecture_design`、`solution_design` |
| 成本与风险 | 给出计算基础、公式、单位、假设和残余风险，不虚构费率或概率 | `cost_analysis`、`risk_analysis` |
| 验证 | 逐项检查候选，不因候选自我声明而通过，不替候选修复 | `verification` |
| 产物合成 | 按请求的 Artifact 合同组织，分离证据、上游结论和未知项 | `artifact_generation` |

## 5. Provider 兼容边界

| Provider 家族 | 结构化输出 | 消息顺序 | 当前结论 |
| --- | --- | --- | --- |
| 通用 OpenAI-compatible | 原生严格 `json_schema` | 保留单一 AgentOS system 前缀后发送 user 请求 | 确定性消息、Schema、流式与排序测试通过；具体厂商端点未逐一认证 |
| GLM / `zhipu` | `json_object` 加传输 Schema 合同和本地校验 | AgentOS system 前缀在前，传输合同追加于其后 | 确定性分支与排序测试通过；未做真实端点认证 |
| 其他配置 Provider | 按通用 OpenAI-compatible 合同 | 同通用路径 | 是否支持严格 Schema/SSE 取决于实际端点 |
| `zhipuai` 标识 | 当前进入通用模型传输分支 | 同通用路径 | 检索路由已识别该别名，但模型传输未归入 GLM/Zhipu 兼容分支，属于待决兼容缺口 |

Provider Adapter 不得决定 Kernel、Preset 或能力策略；Provider/模型及实际结构化输出模式参与实例身份，避免不同传输协议产生相同审计身份。

## 6. 验证结果

### 已确认

- PR-0/PR-1 聚焦测试：`89 passed`；扩展 Prompt/Planner/runtime：`137 passed`。
- PR-1 广泛回归曾显示 `321 passed, 4 failed`，四项均为缺少 async pytest 插件导致的既有环境收集问题；PR-2 已在 requirements 中声明并执行 `pytest-asyncio`。
- PR-2 聚焦测试：`56 passed, 0 failed`；回归 `tests/adapters tests/components/planner tests/runtime`：`337 passed, 0 failed, 44 warnings`。
- PR-3 聚焦测试：`56 passed, 0 failed`，其中 PR-3 专项 `14 passed`。
- PR-3 完整回归曾有一次干净结果：`354 passed, 0 failed, 44 warnings`。随后一次复跑出现 `352 passed, 3 failed, 44 warnings`，均为 `tests/runtime/test_resource_binding.py` 的既有一秒墙钟超时；相同测试在前一轮已通过，且 Runtime/Scheduler 未被本轮修改。
- 静态验证 `python -m compileall -q src service evals`、`python -m json.tool evals/prompt_runtime_pr03_cases.json` 通过；`git diff --check` 无空白错误，仅报告工作树换行符提示。

### 尚未确认

真实模型行为评测尚未运行。评测 Runner 位于 `apps/agentOS/evals/run_prompt_runtime_pr03.py`，默认每个 case 以温度 `0` 执行两次，覆盖：五类注入通道、图规划简约性、四类能力差异、虚假工具声明、Verifier 自我证明抵抗与 Synthesizer 未知项保留。

当前环境缺少 `AGENTOS_MODELS` 和模型凭据，命令：

```powershell
python evals/run_prompt_runtime_pr03.py --runs 2 --temperature 0
```

结果为 `NOT RUN`，已执行观察数为 `0`。因此现有实现具备确定性安全边界和测试覆盖，但没有真实模型行为成功的证据。

## 7. 兼容性与遗留事项

`system_prompt` 和身份元数据保持可选，未迁移调用方继续沿用原有接口。结构化输出、流式事件、超时、重试、故障转移、Token 统计、追踪投影、Schema 校验、能力绑定、拓扑编译和 Artifact 持久化仍由原所有者负责。

后续工作按优先级如下：

1. 在固定 Provider、模型版本和凭据下运行 PR-3 行为评测，并以测量结果替换 `NOT RUN` 状态。
2. 对每个生产 Provider/模型快照执行端点兼容认证，特别确认严格 Schema、SSE 和 GLM/Zhipu 兼容模式。
3. 决定 `zhipuai` 是否并入模型传输的 GLM/Zhipu 兼容分支。
4. 在独立 Runtime/Trace 变更中，将安全身份字段加入失败调用事件的受保护投影白名单。
5. 独立迁移遗留 Agent 字段，清理 44 条弃用警告；此项属于执行模型演进，不应混入 Prompt Runtime 结论。

## 8. 原始材料与追溯

本记录整合自仓库根目录的下列阶段材料，原文保留用于审计追溯：

- `prompt-runtime-pr01-implementation.md`
- `prompt-runtime-pr01-audit.md`
- `prompt-runtime-pr02-implementation.md`
- `prompt-runtime-pr02-audit.md`
- `prompt-runtime-pr02-capability-matrix.md`
- `prompt-runtime-pr03-implementation.md`
- `prompt-runtime-pr03-audit.md`
- `prompt-runtime-pr03-eval-report.md`
- `prompt-runtime-provider-matrix.md`
- `prompt-runtime-followups.md`

当本记录与阶段材料的状态不一致时，以日期更晚、验证范围更明确的材料为准；真实模型评测结果产生后，应更新本记录第 6、7 节的结论。
