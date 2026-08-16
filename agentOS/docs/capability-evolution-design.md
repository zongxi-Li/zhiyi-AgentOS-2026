# AgentOS 统一能力适配与自进化设计

## 目标与阶段边界

本设计包含两个互相独立的部件：统一能力适配和自进化。统一能力适配目前已提供稳定数据合同、进程内注册表，以及不绑定 SDK 的 OpenAI 兼容模型调用入口；自进化仍只提供合同与服务门面。模型密钥、HTTP 客户端、供应商 SDK、算法、持久化和运行时写入均保持在明确的应用层或后续阶段。

## 总体结构

```text
外部生态 / 自研实现
├─ 模型：OpenAI、Anthropic、Google、Azure OpenAI、Bedrock、通义、千帆、智谱、DeepSeek、Ollama、vLLM、OpenAI 兼容端点
├─ Agent：LangChain、LangGraph、AutoGen、CrewAI、LlamaIndex、Semantic Kernel、Haystack、OpenAI Agents、Google ADK、原生实现
└─ Skills / 工具：AgentOS Skill、函数调用、MCP、OpenAPI、HTTP、Python 工具
                 │
                 ▼
contracts/capability.py
├─ CapabilityManifest              能力发现、版本、协议和声明性能力
├─ ModelInvocationRequest/Response 模型调用规范信封
└─ CapabilityInvocation/Result     Agent、Skill、工具统一调用信封
                 │
                 ▼
adapters/
├─ model_compatibility.py           模型供应商协议与注册/解析门面
├─ agent_architecture.py            智能体框架/架构协议与注册/解析门面
└─ skill_tool_compatibility.py      Skill、函数、MCP、OpenAPI 工具协议与注册/解析门面

执行轨迹 ──► contracts/evolution.py ──► components/evolution/
                   │                      ├─ SkillEvolutionService
                   │                      │  评估 → 抽象 → 增/并/分/退提案 → 调度选择
                   │                      └─ GraphEvolutionService
                   │                         轨迹证据 → 图变更提案 → 治理校验 → 离线版本应用
                   ▼
            auditor / recovery / planner
            （审核、恢复补丁与新图版本各自保持边界）
```

## 统一能力适配

`contracts/capability.py` 是外部生态接入的唯一稳定合同。`CapabilityManifest` 描述能力身份、版本、协议和可声明能力；调用时只传递 JSON 兼容的规范请求/结果，禁止将供应商 SDK、框架对象或 MCP 会话对象泄漏到 components 和 runtime。

模型通过 `ModelProviderAdapter.invoke` 接收统一消息、结构化 Schema 与选项。`ModelCompatibilityRegistry` 以 `provider + model` 建立精确路由，要求模型标识声明在 `manifest.capabilities` 中；相同能力 ID 的相同声明可重复登记，不同声明和路由冲突会明确失败。可选同步 `is_available()` 健康检查返回否或抛异常时，解析会拒绝该实例。

`OpenAICompatibleRuntime` 是首个真实调用映射：应用层注入 `JsonTransport` 后，它向 `/chat/completions` 发送 JSON，支持把 `responseSchema` 映射为 OpenAI JSON Schema 格式，并把首个 choice 的 JSON 对象还原为 `ModelInvocationResponse`。SDK 鉴权、流式响应、重试、限流、熔断和观测不在该适配器内实现；它们应由应用层传输或已存在的 Guarded Runtime 组合提供。

智能体通过 `AgentArchitectureAdapter.execute` 映射单 Agent、ReAct、Plan-Execute、Supervisor、层级、Swarm、Graph、事件驱动、Pipeline、辩论、反思和一般多 Agent 架构。AgentOS 的 RuntimeGraph 仍是唯一的运行期执行图；外部框架只能经适配器转换上下文和结果。

Skills 与工具通过 `SkillToolAdapter.invoke` 统一本地 Skill、函数调用、MCP、OpenAPI、HTTP 与 Python 工具。权限裁剪、会话生命周期、参数 Schema 校验、外部副作用审计和失败隔离属于后续实现。

## 图与 Skills 自进化

一次自进化闭环如下：

1. 执行器输出 `Trajectory`，保存任务、动作、反馈、结果、来源技能和图版本。
2. `SkillEvolutionService` 对轨迹计算成功率、效率、新颖度和质量；新颖度是防止技能库同质化的一等指标。
3. 成功轨迹可归纳为候选技能，成功/失败对可对比提炼为因果性更强的候选技能；候选必须包含适用场景、步骤、注意事项与来源轨迹。
4. 服务仅产生 `SkillEvolutionProposal`：新增、合并、拆分或退役。真实入库须经过审核、版本控制和持久化；低新颖度的成功轨迹只更新置信度，不重复入库。
5. 新任务由 `select_for_task` 选出 Top-K 技能供上游注入；执行后的新轨迹再次进入评估，形成闭环。

图演化与运行时恢复必须分离。`GraphEvolutionService` 仅依据历史轨迹生成离线 `GraphEvolutionProposal`，不允许直接修改正在执行的 `RuntimeGraph`。审核通过后，未来的图版本管理器才可用 CAS 和回滚记录写入；实时故障恢复继续使用现有 `GraphPatch`。

| 场景 | 预期提案 | 当前阶段 |
| --- | --- | --- |
| 成功且新颖度高 | 新增候选技能 | 合同/门面已建，算法 TODO |
| 成功但与既有技能高度相似 | 更新置信度或合并提案 | 合同/门面已建，算法 TODO |
| 同一技能在子场景表现分化 | 拆分提案 | 合同/门面已建，算法 TODO |
| 长期未使用或反复造成失败 | 降级、退役提案 | 合同/门面已建，算法 TODO |
| 多条轨迹暴露稳定拓扑瓶颈 | 离线图变更提案 | 合同/门面已建，算法 TODO |

## 文件边界

```text
src/contracts/
├─ capability.py                    外部能力、模型调用和统一调用信封
└─ evolution.py                     轨迹、评分、技能候选及演化提案
src/adapters/
├─ model_compatibility.py           多模型协议和注册/解析门面
├─ agent_architecture.py            Agent 框架协议和注册/解析门面
└─ skill_tool_compatibility.py      Skills/工具协议和注册/解析门面
src/components/evolution/
├─ models.py                        演化合同的内部别名
├─ skill_service.py                 Skills 自进化服务门面
└─ graph_service.py                 图谱演化服务门面
```

依赖方向为：`runtime → components.evolution → contracts.evolution`，`adapters → contracts.capability`。演化部件不得反向依赖特定模型或 Agent 框架；调度、规划和审核只能调用公开服务门面，不可绕过治理层改写技能库或执行图。

## 当前装配与下一步

`runtime.bootstrap.bootstrap()` 会默认提供三个空依赖：`model_compatibility_registry`、`agent_architecture_registry`、`skill_tool_compatibility_registry`。应用层负责创建实际适配器并显式登记，未配置任何外部模型或工具时系统仍可启动，且不会隐式联网。

`AgentProfile` 通过可选的 `modelProvider` 与 `modelName` 声明模型路由。ACG 在 `prepare_run` 时同时校验两项、确认注册表可解析，并将 `{provider, model}` 写入每一步的 `executionState.modelBindings`。节点执行与 checkpoint 恢复只读取这个冻结绑定；`RegisteredModelRuntime` 将原生 `generate_json` 转成统一模型请求，再由 `GuardedModelRuntime` 提供超时、重试、限流和 `commit_id` 幂等边界。未声明模型的旧 Agent 仍可使用显式配置的全局结构化模型运行时。

同一 `provider + model` 可登记多个实现。注册表按 `manifest.metadata.priority` 降序选择，同优先级按 `capabilityId` 固定排序；同步健康检查失败的实现会被跳过。`RegisteredModelRuntime` 若主实现返回临时不可用、限流、超时或供应商暂时失败，会在同一 `commitId` 内切换至下一个健康实现，并让所有候选共用调用者的总超时预算。

应用层可使用 `HttpJsonTransport` 作为 `OpenAICompatibleRuntime` 的 `JsonTransport` 实现。它只接受显式注入的 `base_url`、`api_key` 和 `request_timeout`，默认拒绝 HTTP 明文连接；`api_key` 仅映射为 `Authorization` Header，`commitId` 仅映射为 `Idempotency-Key` Header。HTTP 状态与网络故障会映射为安全错误码，原始响应正文不会进入错误、Trace 或 checkpoint。

应用层可定时调用 `ModelCompatibilityRegistry.refresh_health()` 刷新指定 provider 或模型路由。适配器可选提供 `check_health()` 同步/异步实现；注册表只缓存 `capabilityId → bool`，探测异常、超时或非布尔值均标记为不健康。模型解析和 ACG 节点执行只读取这份缓存与本地适配器状态，不会在任务关键路径隐式联网。

下一阶段应加入模型版本协商、供应商流式输出以及应用层健康刷新调度、密钥轮换/关闭生命周期。外部 Agent 框架只能作为 `AgentArchitectureAdapter` 的被调适实现；ACG 编译、检查点、中断续跑和审计闭环仍由 AgentOS 自身控制。
