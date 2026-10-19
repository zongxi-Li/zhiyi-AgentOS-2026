# PR-EX-00 执行后端架构审计与统一接口设计

> 状态：架构研究与设计文档，未实施。入场基线 master `345ed0a953e1e772e748334294467dfe453bd5a5`（S03-01 冻结提交）。本轮零生产代码修改、零 Commit、零 Push。
> 所有源码结论标注 `文件:行号`（相对 `apps/agentOS/src/`）；外部结论标注公开来源 URL。

## 0. 结论摘要

**知弈 AgentOS 应当以 ACP（Agent Client Protocol）作为外部 Harness 会话层的首选协议，以现有资源平面（Node/Runtime/ModelEndpoint）与 `ResourceExecutionAdapter` 接缝为落点，新增一个最小的 `ExecutionBackend` 端口层（注册/协商/会话/委托/审批/对账），让 ACGNodeRunner 对"进程内 Agent、HTTP 直连后端、ACP 会话后端"无差别调用。内核保留 Mission/Run/GraphVersion、执行许可、调度、审核、恢复与交付身份的全部权威；外部 Harness 只作为被委托的执行者，其权限请求必须回流 AgentOS 审核，其产物只以引用（Receipt/ArtifactRef）形式进入执行状态。**

核心依据：资源平面三层模型已把"执行后端"建为一等公民且明确预留外部 Harness 定位（`contracts/resource.py:62-69` docstring 点名 Local Runtime、ZCode、DSH、Codex、Claude Code）；执行后端与 Agent Role 的解耦已经制度化（`components/resource/embedded_runtime.py`："两层决策互不越界"）；唯一缺口在**会话级执行合同**——当前远程执行是单射请求-响应（`adapters/resource_execution.py`），没有会话、事件流、取消与对账，无法承载有自己 Agent Loop 的 Harness。业界对照（OpenClaw 以 ACP sessions 驱动 Claude Code/Cursor/Copilot/OpenCode/Gemini CLI；DeepSeek Harness 官方提供 dsh-acp）证明 ACP 正是该场景的事实标准。

---

## 1. 当前执行链真实架构

### 1.1 实际存在的链路（生产代码，逐环节标注）

由于 Activation 尚不存在（S03-02 范围），真实入口是 `execute_prepared_run`：

```
ExecutionRuntime.execute_prepared_run (runtime/workflow_runtime.py:987)
  └─ _execute_acg (runtime/acg_execution.py)  ── Pregel 轮次执行编译后的执行图
       └─ 调度装饰器（step 调度期，acg_execution.py:560-700）：
            1. 读冻结需求 execution_state["bindingRequirements"][step]
               （由 RuntimeBindingService.prepare 在 prepare_run 时写入，
                 runtime/binding.py:41-92；来源是编译期 BindingManifest）
            2. 心跳嵌入式后端（acg_execution.py:580-588）
            3. ResourceBinder.bind_ready (components/scheduler/binder.py:232)：
                 硬约束过滤 → 确定性评分 → LeaseCoordinator.acquire
                 → 冻结 ExecutionBinding（含 ModelEndpointBinding）
            4. 分流：
                 a) 远程：_remote_runtime_adapter (acg_execution.py:374)
                    → HttpResourceExecutionAdapter（POST /execute，
                      HMAC 签名 + nonce + Idempotency-Key，
                      adapters/resource_execution.py:55-135）
                    → ResourceAgentProxy 冒充 BaseAgent (resource_execution.py:44)
                 b) 本地：_resolve_embedded_agent 按角色锚点解析进程内 Agent
                    （acg_execution.py:640-648）
            5. 模型绑定：_resolve_model_binding (acg_execution.py:1562)
                 端点绑定优先（binder 冻结）→ Agent Profile 冻结回退
                 → modelBindings[step] → runner.model_runtimes[step]
            6. 持久化 attemptId/stepExecutionId/executionBindings/
               schedulingDecisions（acg_execution.py:650-700）
       └─ ACGNodeRunner.__call__ (components/executor/node_runner.py:159)：
            幂等 commit 检查（value_store 重放，:169-205）
            → prepare_node_commit 先持久化（:208）
            → ContextPack 组装（STRICT/EVENT/DEBATE/BLACKBOARD/broker 五模式）
            → AgentRunContext（含 scoped 工具视图、冻结 model_runtime、
              attemptId、commitId，:384-399）
            → 三级执行调用：resource_adapter.run → agent_invoker.invoke
              → agent.run（:411-417，可重试异常退避重试≤2 次）
            → 输出合同校验 + ExecutionAuditService 审计（先于持久化，:455-474）
            → evidence 授权校验（:486-512）
            → value_store.put_output/put_context_pack 引用化（:545-556）
            → NodeExecutionRecord 状态机推进（contracts/execution.py:37-61：
              PREPARED→EXECUTED→AUDITED→WAITING_REVIEW/COMMITTED/FAILED/CANCELLED）
  审核：ReviewService.apply_acg → apply_review（workflow_runtime.py:2173）
  恢复：ACGCheckpointStore（SQLite 版本 CAS，components/recovery/checkpoint.py:80-124）
        + resume_from_checkpoint（运行锁内互斥，exactly-one-executor 有测试锁定）
```

### 1.2 明确缺失的交接点（Activation 相关）

- **不存在**任何 "Activation" 入口：物化产物停在 `MATERIALIZED_INACTIVE`（`contracts/graph_materialization.py`），没有激活 API、没有正式 Active GraphVersion 权威、没有激活后的执行许可对象。全仓 `GraphVersion` 出现于语义图版本合同（`contracts/evolution.py` 等）与物化记录，但**没有运行时激活检查**：调度装饰器从 `bindingRequirements` 取需求时，不校验"当前图版本是否为正式激活版本"。
- `resume_from_checkpoint` 与恢复协调器不查询物化 Journal（上轮 S03-01 审计已确认，`workflow_runtime.py` 恢复路径 :1991 仅处理既有 Planning Decision）。

---

## 2. 现有能力与缺失能力矩阵

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 资源三层模型（Node/Runtime/Endpoint） | **正式合同+生产链** | `contracts/resource.py:125,166,213`；ResourcePlane 服务 `components/resource/service.py` |
| 执行后端类型学（EXECUTION_BACKEND 含外部 Harness 定位） | **正式合同**（docstring 预留） | `contracts/resource.py:62-69` |
| 后端/角色解耦（Agent Role 非资源） | **正式合同+生产链** | `contracts/resource.py:13-15`；`embedded_runtime.py` 全文 |
| ExecutionRequirement（冻结需求，Planner 无资源权） | **正式合同+生产链** | `contracts/resource.py:252`；`runtime/binding.py:41-92` |
| ResourceBinder 唯一选择权威（硬约束/评分/租约/绑定） | **生产链** | `components/scheduler/binder.py:142-328` |
| 租约协调（内存实现） | **生产链**（单进程） | `components/scheduler/leases.py:91` InMemoryLeaseCoordinator |
| 租约协调（Redis 实现） | **仅有实现，未接通** | `leases.py:176` RedisLeaseCoordinator，生产装配无引用 |
| 远程执行 HTTP 适配（签名/幂等键/安全载荷） | **正式合同+生产链**（单射 RPC） | `adapters/resource_execution.py:55-182`；`acg_execution.py:374-397` |
| 远程执行的会话/事件流/取消/对账 | **不存在** | `ResourceExecutionAdapter` 仅 `async run(ctx)->AgentOutput`（`resource_execution.py:22-24`） |
| Local Runtime（fs/shell 能力、grant 授权、事件流、取消） | **正式合同+生产链**（能力域窄） | `contracts/local_runtime.py`；`adapters/local_runtime.py:20-37` Transport 三方法 |
| 嵌入式 Agent 后端（本进程角色集合） | **生产链** | `embedded_runtime.py`；心跳 `acg_execution.py:580` |
| 模型注册表/兼容性（provider/model/version→adapter） | **生产链** | `adapters/model_compatibility.py`；`RegisteredModelRuntime`（`adapters/model_runtime.py:41`） |
| 模型端点候选（ModelDemand 过滤+弱评分） | **生产链** | `components/resource/service.py:805` model_candidates |
| 模型端点**选择策略** | **不完整**：`bind_ready` 只取第一个候选 | `binder.py:246-254`（`next(iter(...))`） |
| 按 Attempt 冻结模型身份+恢复不换模型 | **生产链** | `acg_execution.py:1562-1628`（端点/Profile 双轨冻结）；`node_runner.py:115-118` |
| GuardedModelRuntime（超时/重试/限流统一控制） | **生产链** | `adapters/guarded_model.py:108` |
| 流式模型事件（TTFT/idle/total、activity 保活） | **生产链** | `adapters/model_runtime.py:385-659` |
| 节点幂等提交/重放（value store 唯一真源） | **生产链** | `node_runner.py:169-208`；`components/executor/value_store.py` |
| 节点收据（NodeExecutionRecord 状态机） | **正式合同+生产链** | `contracts/execution.py:37-61` |
| 审计/审核（先持久化后写库；WAITING_REVIEW 中断） | **生产链** | `node_runner.py:455-485`；`checkpoint.py:27-40` ExecutionInterrupt；`workflow_runtime.py:2173` |
| 工具白名单+作用域收窄 | **生产链** | `adapters/audited_tool_runtime.py:25-51`（scoped）；`node_runner.py:375-383` |
| 工具级**人工审批回路**（ApprovalRequest 概念） | **不存在**（仅白名单拒绝） | 全仓无 ApprovalRequest 合同 |
| 检查点版本 CAS + 断点恢复 | **生产链** | `checkpoint.py:80-124` |
| Activation / 正式 GraphVersion 权威 / 执行许可 | **不存在**（S03-02） | §1.2 |
| BackendCapabilities 协商 / 后端会话 / 委托凭据 / 对账快照 | **不存在** | 全仓检索无对应合同 |
| 资源签名凭据（注册/轮换/防重放 nonce） | **生产链** | `components/resource/auth.py`；`resource_execution.py:90-111` |

**三者耦合检查结论**：执行后端（Runtime）、执行模型（RuntimeKind+Placement+Trust）、Agent Role（嵌入式角色锚点 `agent:<role>`）在合同层已正交。唯一残余耦合：`_resolve_model_binding` 的 Profile 回退路径把"Agent 角色画像"当作模型路由兜底（`acg_execution.py:1595+` `_freeze_model_binding`）——这是兼容行为，非权威（docstring 自认"只是兼容性偏好，不构成资源事实"），设计上应在 Model Routing 显式化后降级为显式默认策略。

---

## 3. 外部项目对照

### 3.1 OpenClaw（github.com/openclaw/openclaw）

- **定位**：本地个人 AI 助手网关；模型与 agent harness 均为可替换插件（官方 README："Models and agent harnesses (Claude, Codex, local models) are plugins you can swap"）。
- **Harness 注册与选择**：harness registry + per-model/provider 域的 `agentRuntime.id` 策略；`auto` 选择"支持当前 provider 路由的已注册插件 harness，否则内置运行时"（docs.openclaw.ai/agent-runtime-architecture）。运行时代码 `src/agents/harness/`（registry、selection policy、lifecycle）。
- **外部 Harness 委托**：**官方以 ACP sessions 运行外部 coding harness**——Claude Code、Cursor、Copilot、Droid、OpenClaw ACP、OpenCode、Gemini CLI 等（docs.openclaw.ai/tools/acp-agents："Agent Client Protocol (ACP) sessions let OpenClaw run external coding harnesses"）。另提供 `openclaw/acpx`：面向编排器的**无头 ACP 客户端 CLI**（结构化接口驱动有状态 ACP agent）。
- **运行时快照**：Gateway 每次发布构建"一个 prepared model runtime generation"（auth 模板+模型注册表+目录的原子快照），过期/残缺快照绝不对外服务——与 AgentOS 的"按 Attempt 冻结绑定"同哲学。
- **会话/权限/沙箱**：文档页未完整公开权限模型；社区分析指出 session、memory、tool sandboxing、access control 是其一等概念。

### 3.2 ZCode（Z.ai 智谱）

- **定位**：Z.ai 的终端 coding agent（CLI/TUI），深度绑定 GLM-5.x 与 GLM Coding Plan（github.com/zai-org/GLM-5；topics/zcode 下有第三方插件与 ZUSC 非官方安装器）。
- **公开合同状态：缺失**。官方 CLI 源码未开放；zai-org/feedback issue #749 仅讨论"自编译 CLI + `zcode login` 是否保留订阅权益"。**没有公开的 App Server 协议规范、会话/事件接口文档**。
- **结论**：产品存在性可核实，但接入不能建立在未公开合同上。可选路径只有 (a) CLI 子进程 + 文件级工作区协议（黑盒）；(b) 等官方开放协议。任何"ZCode 事件接口"的描述在公开层面都属于**无法确认**，本设计不依赖它。本仓库 `contracts/resource.py:66` 已把 ZCode 列为预期后端，登记为"待官方合同"。

### 3.3 DeepSeek Harness / dsh（github.com/deepseek-ai/deepseek-harness）

- **定位**：基于 Cordis 元框架（论文 "A Programming Paradigm for Spatiotemporal Composability"）的开源 agent harness；"everything is a plugin"——模型、工具、记忆、会话、沙箱、agent loop、UI 皆插件（官方 README）。
- **ACP**：官方维护 `deepseek-ai/dsh-acp`（ACP server 实现）；社区另有 openma-ai/deepseek-harness-acp。**已证实的集成痛点**：ACP 传输 stdio-only，多租户集成方需要自建传输层（官方 Discussions #4692、#4693"papercuts"）。
- **成熟度**：developer preview，官方声明预期破坏性变更。接入需版本钉死 + ACL 隔离。

### 3.4 OpenHands / Software Agent SDK（github.com/OpenHands/software-agent-sdk）

- **四包架构**：`openhands.sdk`（agent/LLM/conversation/events/skills/condensers/security）+ `tools`（Action/Observation/Executor 模式）+ `workspace`（Docker/RemoteAPI 隔离工作区）+ `agent_server`（FastAPI 无头远程执行，REST+WebSocket：conversations、bash、files、events、desktop、VSCode；另暴露 OpenAI 兼容 `/v1/chat/completions`、`/v1/responses`；per-user 隔离会话+API key）。
- **事件溯源**：不可变类型安全事件构成 append-only log，驱动执行与状态（docs.openhands.dev/sdk/arch/events；arXiv 2511.03690 论文含确定性重放）。Agent 无状态+配置不可变，Conversation 持有状态——与 AgentOS "NodeRunner 无状态、State/checkpoint 唯一真源"同构。
- **对照价值**：其 Agent Server 是"HTTP 直连执行后端"的最完整参照（含会话生命周期与事件流），AgentOS 现有 `HttpResourceExecutionAdapter` 相当于其无会话子集。

### 3.5 对照总结

| 维度 | OpenClaw | ZCode | dsh | OpenHands | AgentOS 现状 |
| --- | --- | --- | --- | --- | --- |
| 接入方式 | 插件 SDK + ACP sessions | CLI（无公开合同） | 插件 + 官方 ACP(stdio) | REST/WS SDK | HTTP 单射 RPC + 进程内 |
| 会话生命周期 | ACP session（new/load/prompt/close） | 不可核实 | Cordis session 插件 + ACP | conversation（REST 资源） | **无** |
| 事件流/回放 | session/update 流 | 不可核实 | 插件事件 | append-only event log + WS | 模型流有；节点级无 |
| 权限/审批 | ACP request_permission | 不可核实 | ACP request_permission | 安全策略+沙箱 | 白名单+审计，**无审批回路** |
| 取消/恢复 | session/cancel | 不可核实 | ACP cancel | 会话级 | Run cancel；**远程执行不可取消** |
| 工作区隔离 | sandbox（细节未公开） | 不可核实 | sandbox 插件 | Docker workspace | Local Runtime grant 工作区 |
| Windows 适配 | 良（Node 系） | 良（本机在用） | 未验证 | Docker 依赖重 | 本机开发环境 |
| 版本稳定性 | 主版本活跃 | 闭源 | **preview，breaking** | v1 SDK | 内部冻结 |
| 对 AgentOS 侵入 | ACP client 侧低 | 高（黑盒 CLI） | ACP client 侧低 | REST 低 | — |

---

## 4. 协议选择：ACP 为主、A2A 备选、MCP 限工具层、原生直连兜底

### 4.1 ACP（Agent Client Protocol，agentclientprotocol.com，v1/v2）

JSON-RPC 2.0（以 stdio 为主传输）。角色定义与 AgentOS 权威模型**同构**：Client（IDE/宿主）"管理环境、用户交互与资源访问"，Agent 是被驱动的 coding agent——把 AgentOS 放在 Client 位，外部 Harness 放在 Agent 位，"内核拥有环境与审批权"就直接成为协议语义而非附加约束。

- 会话：`initialize`（版本/能力协商）→ `session/new`/`session/load`（loadSession 能力）→ `session/prompt`（一轮，流式 `session/update` 通知：消息块/工具调用/计划/压缩）→ 响应带 stop reason；`session/cancel`（通知）中断；v2 稳定化 `session/close`（agentclientprotocol.com/updates：Session Close RFD 完成）。
- **审批回路（关键）**：Agent → Client 的 `session/request_permission` 是基线方法；Client 侧可选 `fs/read_text_file`、`fs/write_text_file`、`terminal/*`、`elicitation/create`。即外部 Harness 的每次敏感操作都要回到 Client（AgentOS）授权——**这正是任务书要求的"第三方 Harness 不得取得内核权威"的协议化表达**。
- 扩展：`_meta` 字段、下划线前缀自定义方法、initialize 时自定义能力广播——为 AgentOS 私有扩展（收据上报、执行许可验证）留了正式通道。
- 实证：OpenClaw 官方文档以 ACP sessions 驱动七种外部 harness；dsh 官方 dsh-acp；Zed/JetBrains 作为 Client 实现（jetbrains.com/acp）。已知限制：stdio-only 传输（dsh #4692）——对 AgentOS 是进程内子进程模型，可接受，跨机部署需自建桥（登记为部署约束，不阻塞合同设计）。

### 4.2 A2A（a2aproject/A2A，LF 治理）

面向 **opaque agent 之间**的互操作：AgentCard 发现、JSON-RPC over HTTP(SSE/WS)、Task 状态机（submitted/working/**input-required**/completed/failed/canceled）、不可变 Artifact+Part（官方 spec docs/specification.md；agent2agent.info/docs/concepts/task）。**定位为备选**：当对端是"别人家的 Agent 服务"而非"我们委托的执行后端"时使用。不作为主执行通道的理由：无权限审批回路（不适合受控执行）、Task 粒度与 AgentOS Run/Step 映射粗糙、语义为对等协作而非委托。

### 4.3 MCP（modelcontextprotocol.io）

工具/资源/prompt 三原语 + Client 反向能力（sampling/roots/elicitation；用户同意集中在 Client）。**限定为工具层协议**：对应 `RuntimeKind.TOOL_SERVICE`（`contracts/resource.py:71`），AgentOS 已有 audited tool runtime 白名单/scoped 语义可承接。不承载执行会话。

### 4.4 原生 SDK / 签名 HTTP（现有模式增强）

自有后端（Local Runtime）与未实现 ACP 的后端走现有 `ResourceExecutionAdapter` 接缝升级版（签名/幂等键保留）。OpenHands Agent Server 归此类（REST 资源化会话）。

---

## 5. 推荐设计模式与取舍

| 模式 | 适用点 | 证据/理由 | 取舍 |
| --- | --- | --- | --- |
| Ports & Adapters | `ResourceExecutionAdapter` Protocol（`resource_execution.py:22`）是现成端口；新增 `ExecutionBackend` 端口同构 | 已被 Local/HTTP 两实现验证 | 端口方法必须最小；避免泄漏 AgentRunContext 全量（现有 `build_remote_execution_payload` 只传步骤合同子集，:185-201——保持） |
| Strategy | 模型端点选择从 binder 内联逻辑显式化为可注入策略 | `bind_ready` 现取第一个候选（`binder.py:246`） | 策略无资格裁决权，资格仍在硬约束 |
| Registry | 后端注册表复用 ResourcePlane（RuntimeProfile 即注册单元）+ ModelCompatibilityRegistry 先例 | `service.py:355` register_runtime | 不建第二注册表 |
| Actor-like Session | `ExecutionSession`：单会话单所有权、顺序 turn、邮箱式事件缓冲 | ACP session/prompt turn 语义 | 会话无自主生命周期：创建/关闭由 AgentOS Attempt 驱动 |
| Anti-Corruption Layer | ACP/各家事件 → `RuntimeEvent`（`contracts/runtime_events.py`）翻译层；外部工具调用 → AgentOS 工具审计 | 流式模型事件已示范翻译边界（`model_runtime.py:494-512` emit/seq） | 翻译层不回写外部系统状态 |
| Outbox/幂等 | 委托与收据沿用 prepare→commit 模式（node commit 先持久化，`node_runner.py:206-208`） | S02 系列已验证 | 外部副作用无法 exactly-once，只承诺 at-least-once + 幂等键去重 |

**否决的候选**：(a) 把外部 Harness 直接注册为 BaseAgent（现有 ResourceAgentProxy 模式的无会话扩展）——丢失事件流/审批/取消，且把外部多步 Loop 压扁成单次调用；(b) 以 A2A 为统一执行协议——无审批回路；(c) 为每个后端写专用集成层——重复合同，违反"禁止平行合同"。

---

## 6. 统一 ExecutionBackend Contract 草案

### 6.1 概念复用映射（先复用，后新增）

| 任务书概念 | 处置 | 证据 |
| --- | --- | --- |
| BackendCapabilities | **新增**（薄）：会话/审批/取消/快照/模型自管 五布尔 + ACP 能力对象透传 | initialize 协商结果无处安放 |
| BackendDescriptor | **复用** RuntimeProfile（+metadata 扩展协议版本/实现标识） | `contracts/resource.py:166`；endpoint 字段已有 |
| ExecutionSession | **新增**：一次 Attempt 内与后端的会话投射（sessionId、backendSessionRef、状态、能力快照） | 无对应物 |
| ExecutionAttempt | **复用**现有 attempt_id/stepExecutionIds 语义（`acg_execution.py:565-569`），**新增**会话-attempt 关联投影，不新建第三套 ID | 现有身份已持久化且被恢复链使用 |
| ExecutionDelegation | **新增**：AgentOS→后端的委托凭据（grant 引用模型，仿 LocalRuntimeAuthorizationRef，`contracts/local_runtime.py:44`） | 签名头是传输细节，需要合同级凭据 |
| ExecutionEvent | **复用** RuntimeEvent（eventType/runId/nodeId/attemptId/sequence/payload） | `contracts/runtime_events.py`；model.* 事件族已示范 |
| ExecutionApprovalRequest | **新增**：审批请求（对端工具调用→AgentOS 审核→应答），内部衔接 ReviewService/工具审计 | 全仓无此合同 |
| ExecutionSnapshot | **新增**：对账快照（后端侧执行进度引用，用于断线/崩溃后 reconciliation） | 无对应物 |
| ExecutionReceipt | **复用+扩展** NodeExecutionRecord：加 graphVersion、backendSessionRef、副作用清单（side-effect ledger 引用） | `contracts/execution.py:47` |
| BackendArtifactReference | **复用** value store 引用模式（outputRef/contextRef 字符串）+ ContentManifest；新增 backend 侧 digest | `node_runner.py:545-556`；artifacts 合同已存在（`contracts/artifacts.py`） |

### 6.2 端口定义（草案，Python Protocol 风格）

```python
class ExecutionBackend(Protocol):
    """一个已注册 EXECUTION_BACKEND 的会话化执行端口。

    生命周期：AgentOS 按 Attempt 建立 Session → 逐 turn prompt（事件流回调）
    → 终态收据。实现方负责 ACL：外部事件先翻译为 RuntimeEvent 再进入内核。
    """
    descriptor: RuntimeProfile                      # 复用注册画像

    def capabilities(self) -> BackendCapabilities: ...

    async def open_session(self, delegation: ExecutionDelegation,
                           attempt: AttemptContext) -> ExecutionSession: ...

    async def prompt(self, session: ExecutionSession, turn: ExecutionTurn,
                     sink: ExecutionEventSink) -> TurnStopReason: ...
        # sink: 已过滤/翻译为 RuntimeEvent 的事件出口；审批请求经 sink.approval()

    async def request_cancel(self, session: ExecutionSession) -> None: ...

    async def snapshot(self, session: ExecutionSession) -> ExecutionSnapshot: ...

    async def reconcile(self, delegation: ExecutionDelegation,
                        snapshot: ExecutionSnapshot) -> ReconciliationVerdict: ...
        # 断线/重启后对账：completed/in-flight/unknown(→安全侧失败)

    async def close_session(self, session: ExecutionSession) -> None: ...
```

要点：
- **turn** 是委托单位（对应一个 ACG 节点的执行请求），不是 Run、不是外部 Loop 的一步——外部多步 Loop 全部发生在后端黑盒内，只在事件流与终态收据处显形。
- `TurnStopReason` 对齐 ACP stop reason + 本地语义（end_turn/cancelled/max_tokens/error/client_tool_failure…）。
- **不确定结果**：`reconcile` 返回 unknown 时按失败处理并登记副作用台账，绝不自动重发非幂等操作——这是对"不得承诺 exactly-once"的制度化。
- 旧 `ResourceExecutionAdapter.run` 保留为无会话退化路径（`LocalResourceExecutionAdapter`、嵌入式 Agent 直接实现"单 turn 后端"的退化特例），`HttpResourceExecutionAdapter` 升级为无会话后端的传输细节。

### 6.3 任务书第五节十问的逐问回答

1. **Run 与 BackendSession**：一次 Run 的每个 Attempt 至多一个 Session；Session 生命周期严格包含于 Attempt；Run 级不跨后端共享会话（隔离旧/新图版本的前提）。
2. **ACG Node 与后端内部 Loop**：Node = 一个 turn（委托单位）；后端内部任意多步 Loop 是实现细节，只通过事件流（可观测）与终态（可信）显形。Planner 的图语义不被后端 Loop 重写。
3. **ID 区别**：`commitId`=幂等键（node_runner 重放）；`attemptId`=一次执行尝试身份（调度/绑定/恢复单位）；`stepExecutionId`=执行实例引用；SessionId=AgentOS 侧会话身份；backendSessionRef=对端会话引用（透传不可解释）；**外部副作用 ID**（对端工具调用/文件变更）单独台账（side-effect ledger），以 (对端操作 ID, 幂等键) 去重——绝不与 commitId 混同。
4. **状态语义**：委托后 AgentOS 侧 Attempt 处于 IN_FLIGHT；终态映射 completed/failed/cancelled/**indeterminate**（对账后收敛为 failed+台账，或 completed+证据）；PREPARED 先持久化的既有模式（node_runner.py:206）延伸到 turn 粒度。
5. **事件转换**：外部事件一律经 ACL 翻译为 RuntimeEvent（补 runId/nodeId/attemptId/sequence），模型流已有先例（model.* 事件族）；不可信字段（原始 prompt、对端内部状态）不进入 payload——沿用"输出合同校验+引用化"。
6. **审批**：对端 `request_permission`/工具敏感调用 → ExecutionApprovalRequest → AgentOS 审核（衔接既有 ExecutionAuditService/ReviewService：策略自动裁定量走 audited runtime，需人工量走 WAITING_REVIEW 通道）→ 应答仅授权"本次调用"，不扩大会话权限。
7. **断线/崩溃/超时对账**：turn 有 total deadline（复用模型流三段式思想）；超时→request_cancel→snapshot→reconcile；进程重启后按 delegation ID + backendSessionRef 向后端查询快照；不可恢复或后端无响应→按 indeterminate 登记失败并释放租约。要求后端能力声明 `supportsReconcile`。
8. **无会话恢复的后端**：BackendCapabilities.supportsSessionResume=false 时，Attempt 级故障即失败收敛（不续用旧会话），重试开新 Attempt——安全降级路径与嵌入式 Agent 现状一致。
9. **同一会话多轮交互**：仅当同一 Attempt 内的多个 turn（如 Debate/交互式节点）且每 turn 都在授权任务边界内；跨 Attempt 复用会话默认禁止（模型/绑定已按 Attempt 冻结，`acg_execution.py:656`），需显式策略白名单。
10. **产物与证据**：后端产物以 digest+引用入 ContentManifest/value store（复用 `_persist_artifact_manifest` 模式，node_runner.py:992）；收据（Receipt）记录 graphVersion/attempt/session/副作用清单；交付身份始终由 AgentOS 签发。

---

## 7. 身份与状态模型

```
Mission ── Run ── (S03-02: Activation → ExecutionPermit{graphVersion, namespace})
                    └─ Attempt ── ExecutionBinding(runtime, modelEndpoint, lease)
                          └─ ExecutionSession (≤1/Attempt) ── backendSessionRef
                                └─ Turn(s) ── NodeExecutionRecord(收据)
                                      └─ SideEffectLedger(外部副作用 ID 台账)
```

- 收据归属扩展：NodeExecutionRecord 增 `graphVersion`（激活版本）、`sessionRef`、`sideEffectRefs`；归属链 Run→GraphVersion→Attempt 由收据可追溯（满足任务书第七节"收据如何归属"）。
- 已完成前缀防重执行沿用 commitId 幂等重放（node_runner.py:169-205），激活切换后的新版本图前缀保护由 S03-02 Safe-Cut 既有语义承担（S02-03 已验收）。

## 8. 权限、隔离、副作用与恢复方案（要点）

- **权限**：委托凭据（ExecutionDelegation）= 系统签发 grant 引用（仿 LocalRuntimeAuthorizationRef"不携带访问策略"哲学，contracts/local_runtime.py:44-49）；对端 fs/terminal 请求回落到 AgentOS 的 grant/审批裁决，绝不透传宿主全权。工具白名单按步骤 scoped（audited_tool_runtime）延伸到后端 turn 级。
- **隔离**：Placement/TrustLevel/DataZone 硬约束（binder.py:40-86）继续作为资格闸门；外部 Harness 默认 SANDBOXED 信任档，本地受信设备档需显式运维标注；工作区按 Run namespace 隔离（Local Runtime grant 已有 workspace_id 概念）。
- **副作用**：非幂等外部调用只承诺 at-least-once + 台账去重 + 审批前置；副作用清单进入收据，交付前可见。禁自动重试已发生不确定结果的 turn。
- **恢复**：checkpoint（SQLite CAS）+ reconcile 快照双轨；exactly-one-executor 互斥（既有测试锁定）扩展到会话级：Attempt 存活期间二次进入仍被拒。

## 9. Backend Selection 与 Model Routing 分离

现状闭环度：Runtime 选择闭环完整（硬约束+评分+租约）；模型端点"过滤+弱评分"存在但**选择策略缺位**（取第一个）；按 Attempt 冻结与恢复不换模型已闭环；Profile 兜底是兼容残迹。

设计：

```
bind_ready(step/attempt):
  runtime_choice   = RuntimeStrategy.score(candidates)        # 既有评分
  model_choice     = ModelEndpointStrategy.resolve(           # 新显式策略（可注入）
        mode ∈ {BACKEND_MANAGED,            # 后端自管（ExternalBackend 无 modelBinding）
                AGENTOS_EXPLICIT,           # Planner/运维显式指定 → ModelDemand 软偏好升级为指令
                AGENTOS_ALLOWLIST,          # ModelDemand.allowedEndpointIds（现状已有字段）
                PINNED_REJECT})             # 端点不可用 → FATAL NO_MODEL_ENDPOINT（现状已 fatal）
  → 单一提交点冻结 ExecutionBinding(含 ModelEndpointBinding)   # 语义不变，实现显式化
```

- 四模式即任务书第六节五要求；`NO_MODEL_ENDPOINT` 已在 FATAL_SCHEDULING_REASONS（scheduler/models.py:34-38）满足"固定能力不可用时明确拒绝"。
- 失败后重绑：仅新 Attempt 允许（恢复策略裁决），Attempt 内不可变——与现行冻结语义一致，无需改合同。
- Planner 只出 ModelDemand（能力+偏好），无分配权——现状已满足，保持。

## 10. S03-02 必须预留的接口与最小改动建议

（本轮不实现，仅冻结衔接合同要点）

1. **ExecutionPermit**：Activation 成功的持久产物 = {runId, graphVersion, packageChecksum, activationId, namespace}；`bind_ready` 增加前置校验"该 Attempt 携带有效 Permit"（建议做成 binder 入参而非 binder 内部查询，保持 binder 无状态权威语义）。
2. **READY→租约**：现状已是"调度期即时 bind"；预留 `ExecutionPermitVerifier` 注入点，Scheduler 交接（未来外部调度器）以 Permit 为唯一执行许可来源。
3. **收据加列**：NodeExecutionRecord 增 graphVersion/sessionRef/sideEffectRefs（向后兼容默认值）。
4. **版本隔离**：Run 内 activation 切换后，旧版本 in-flight Attempt 的会话按"完成或取消"收敛，新 Attempt 绑定新 Permit——ExecutionSession 归属 Attempt 的设计（§7）已隔离，无需会话级迁移。
5. **恢复对账**：resume_from_checkpoint 路径增加"Attempt IN_FLIGHT → reconcile 后端快照"步骤（capabilities.supportsReconcile=false 时直接失败收敛）。
6. **最小改动约束**：上述全部落在 acg_execution 调度装饰器与合同扩展层，不触碰 NodeRunner 管线、value store 语义与 S02 冻结链。

## 11. EX-01 / EX-02 分阶段实施计划

**EX-01（合同与最小后端，一个 PR）**：
- 新增 `contracts/execution_backend.py`（§6.1 新增件：BackendCapabilities/ExecutionSession/ExecutionDelegation/ExecutionApprovalRequest/ExecutionSnapshot + Receipt 扩展列）；BackendDescriptor 复用 RuntimeProfile。
- `ExecutionBackend` 端口 + `EmbeddedSingleTurnBackend`（包装现有本地路径）+ `HttpResourceExecutionAdapter` 升级为无会话后端实现（行为不变，合同化）。
- ModelEndpointStrategy 显式化（§9），bind_ready 行为等价重构 + 测试。
- 对抗测试：审批回路、取消、reconcile-indeterminate、Permit 缺失拒绝（为 S03-02 预热的假实现）。

**EX-02（ACP 适配与真实外部 Harness，一个 PR）**：
- `AcpBackend`：stdio 子进程 + JSON-RPC（initialize/session new|prompt|cancel|close/request_permission），ACL 事件翻译为 RuntimeEvent；`_meta` 扩展收据上报。
- 以 OpenCode/Gemini CLI/任意 ACP agent 作验收对象（公开可核实、可自动化）；dsh 经 dsh-acp 验收（版本钉死，登记 preview 风险）。
- ZCode：仅在"官方公开合同出现"后进入；当前登记为黑盒 CLI 待定。
- OpenHands Agent Server 作原生 HTTP 会话后端第二验收对象。
- 副作用台账 + 交付前对账流程落地。

---

## 附录 A：无法确认的部分

- ZCode 的 App Server/会话/事件接口：无公开正式文档（zai-org 公开仓库仅有模型卡与反馈 issue #749）；本文一切设计不依赖其存在。
- OpenClaw 权限/沙箱模型细节：官方架构页未公开完整权限模型，本文仅采信其 ACP sessions 能力陈述。
- dsh 生产稳定性：官方 developer preview 声明，未验证。
- ACP v2 细节（session/close 稳定化）以 agentclientprotocol.com/updates 为准，本文按 v1 基线 + v2 已知增量设计。

## 附录 B：主要来源

源码：文中行号均对应 master `345ed0a9`。外部：openclaw/openclaw 与 docs.openclaw.ai（agent-runtime-architecture、tools/acp-agents、cli/acp）；openclaw/acpx；deepseek-ai/deepseek-harness 与 Discussions #4692/#4693、deepseek-ai/dsh-acp；OpenHands/software-agent-sdk 与 docs.openhands.dev/sdk/arch/overview、/sdk/arch/events、arXiv:2511.03690；agentclientprotocol.com（protocol/v1/overview、/v1/schema、/updates）；a2aproject/A2A docs/specification.md、agent2agent.info/docs/concepts/task；modelcontextprotocol.io/specification（client/sampling、roots、elicitation）；zai-org/GLM-5、zai-org/feedback#749、github.com/topics/zcode。
