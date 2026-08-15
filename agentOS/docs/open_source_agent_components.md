# AgentOS 开源智能体生态调研与组件选型

> 调研日期：2026-08-10。仓库元数据来自 GitHub Repository / Commit API；源码快照位于 `references/open-source/`。
> 
> 许可证仅用于初步筛选，不构成法律意见。任何复制、修改、发布或商用前，必须复核仓库根目录与目标子目录的 `LICENSE`、NOTICE、依赖许可证及商标条款。

## 1. 当前 AgentOS 对应关系

```text
AgentOS 现有层                         借鉴目标
──────────────────────────────────────────────────────────────────
components/planner/                    角色、能力路由、任务图、规划变体
components/task_manager/               任务状态、优先级、工作流登记
components/scheduler/                  资源评分、租约、执行包
components/executor/                   图执行、并发批次、屏障、人工中断
components/communicator/               消息、上下文压缩、血缘、可靠投递
components/memory/                     记忆写入、召回、向量索引、生命周期
components/auditor/                    事件、证据、策略判定、可观测性
components/recovery/                   检查点、重试、图补丁、恢复策略
adapters/                              模型、工具、存储、远程 Agent 的具体实现
tools/                                 ACG JSON、Mermaid、DOT 导出
```

## 2. 候选仓库与可用组件

| 仓库 | 许可证（GitHub 元数据） | 优先借鉴模块 | 对应 AgentOS | 复用结论 |
|---|---|---|---|---|
| [LangGraph](https://github.com/langchain-ai/langgraph) | MIT | StateGraph、持久化检查点、interrupt、人审续跑、图版本 | executor、recovery、runtime | 可作为图执行与恢复算法参考；保留 MIT 版权声明后可评估代码级复用。 |
| [OpenHands](https://github.com/OpenHands/OpenHands) | MIT | Agent 事件流、工具动作、沙箱执行、运行轨迹 | executor、auditor、adapters/tool | 可参考事件/动作模型与执行隔离；不建议把完整开发平台直接嵌入运行时。 |
| [CrewAI](https://github.com/crewAIInc/crewAI) | MIT | Agent 角色、Task、Crew、Flow、流程编排 | planner、task_manager、scheduler | 可参考角色—任务的建模与 Flow DSL；现阶段源码归档未完整校验。 |
| [Mem0](https://github.com/mem0ai/mem0) | Apache-2.0 | 记忆抽取、记忆更新、向量检索、实体关系 | memory、adapters/storage | 高优先级参考；适合补全混合召回与记忆巩固。复用须携带 Apache-2.0 许可证与 NOTICE。 |
| [Haystack](https://github.com/deepset-ai/haystack) | Apache-2.0 | Component/Pipeline、Router、DocumentStore、Retriever | planner、communicator、memory、adapters | 可参考可组合 Pipeline 与检索 Adapter；避免引入整个框架造成双编排器。 |
| [AutoGen](https://github.com/microsoft/autogen) | CC-BY-4.0 | 消息驱动 Agent、Team / Group Chat、工具调用 | communicator、executor、auditor | 适合接口与事件模型参考；代码级复用须逐项确认 CC-BY 署名、声明与软件分发适配性。 |
| [AutoGPT](https://github.com/Significant-Gravitas/AutoGPT) | Other / NOASSERTION | Block/Workflow 平台、Agent 构建体验、插件生态 | planner、runtime、tools | 仅做架构与产品参考；当前许可证不是可直接拷贝代码的充分授权。 |

## 3. 建议采用的实现点

```text
P0：先实现，不引入第三方运行时依赖
├─ LangGraph 思路
│  ├─ executor/graph.py：图状态、条件边、可恢复状态机
│  ├─ recovery/checkpoint.py：版本化检查点、interrupt 后继续
│  └─ runtime/workflow_runtime.py：人审/恢复的明确状态转换
├─ OpenHands 思路
│  ├─ executor/dispatcher.py：统一 Action → Observation 事件
│  ├─ auditor/governance/trace.py：追加式事件与工具轨迹
│  └─ adapters/tool/：工具超时、取消、隔离与结果标准化
└─ 产物：保持 AgentOS contracts 为唯一合同，不直接嵌入外部框架对象

P1：以 Adapter 接入
├─ Mem0：实现 MemoryStore 的向量检索 Adapter、记忆抽取/合并策略
├─ Haystack：实现检索、重排、文档存储 Adapter；不使用其顶层 Pipeline 替代 AgentOS runtime
└─ 模型/工具：以 adapters/model 与 adapters/tool 的 Protocol 为唯一注入点

P2：仅借鉴建模与用户体验
├─ CrewAI：规划角色、任务依赖、顺序/层级工作流表达
├─ AutoGen：多 Agent 消息拓扑、发言/终止条件、事件日志
└─ AutoGPT：可视化 Block、工作流模板与扩展市场的产品设计
```

## 4. 不建议直接引入的内容

| 风险 | 处理原则 |
|---|---|
| 双编排器 | 不同时让 LangGraph / Haystack Flow / CrewAI Flow 接管 AgentOS `runtime`；仅将其算法或 Adapter 封装在现有 Interface 后。 |
| 双记忆源 | 不让 Mem0 / Haystack DocumentStore 绕过 `components/memory/service.py` 直接写入业务状态。 |
| 外部合同泄漏 | 外部框架的 Message、State、ToolResult 先转换为 `src/contracts/` 模型。 |
| 许可证误用 | AutoGPT 与 AutoGen 不纳入可直接复制代码清单；MIT/Apache 代码也必须保留要求的通知。 |
| 沙箱越权 | OpenHands 类终端/浏览器工具必须通过 `adapters/tool` 注入，并保留权限、审计、取消与资源限制。 |

## 5. 源码快照清单

| 仓库 | 分支 / 快照 | 本地位置 | 状态 | 备注 |
|---|---|---|---|---|
| LangGraph | `main` / `d56666f7fbf0d380ad84cdf0cbe5aa48ab0cc086` | `references/open-source/langgraph-source/` | 完整解压 | 670 个文件；归档 `langgraph-main.zip` 已校验。 |
| OpenHands | `main` / `e8e6f45cc8f0c53bc1e757f2c6254c439ed04810` | `references/open-source/openhands-source/` | 完整解压 | 2027 个文件；归档 `openhands-main.zip` 已校验。 |
| AutoGen | `main` / `027ecf0a379bcc1d09956d46d12d44a3ad9cee14` | `references/open-source/autogen-source/` | 部分可读 | 已解出主要源码；归档内 PDF 条目损坏，不能视为完整可复用快照。 |
| AutoGPT | `master` / `ce6ab7b074a625ce591c1f41ef17276c8093087d` | `references/open-source/autogpt-master.zip` | 待重下 | 并发下载超时导致归档校验失败。 |
| CrewAI | `main` / `17f107c197e64ea486a1c985a36b3c4aecb20d28` | `references/open-source/crewai-main*.zip` | 待重下 | 网络限速导致断点续传未在本轮完成。 |
| Mem0 | `main` / `4debc58a83377b18be81ae1e5969a300736b2fac` | `references/open-source/mem0-main.zip` | 待重下 | 并发下载超时导致归档校验失败。 |
| Haystack | `main` / `842519e5e4b9ab755b7b7d1672f53f4a3841c197` | `references/open-source/haystack-source/` | 待重下 | 解压目录为空，不可作为源码参考。 |

## 6. 下载与校验方式

```powershell
# Git HTTPS 可用时：保留 Git 历史的浅克隆
git clone --depth 1 https://github.com/langchain-ai/langgraph.git references/open-source/langgraph

# Git HTTPS 受限时：下载 GitHub 默认分支源码归档
Invoke-WebRequest `
  -Headers @{ 'User-Agent' = 'AgentOS-research' } `
  -Uri 'https://api.github.com/repos/langchain-ai/langgraph/zipball/main' `
  -OutFile 'references/open-source/langgraph-main.zip'

# 校验归档可读取后再解压
tar -tf references/open-source/langgraph-main.zip
Expand-Archive references/open-source/langgraph-main.zip `
  -DestinationPath references/open-source/langgraph-source
```

## 7. 后续实施清单

```text
├─ [ ] 为 recovery/checkpoint.py 增加版本号、CAS 与持久化 Adapter
├─ [ ] 为 executor/dispatcher.py 建立 Action / Observation 标准事件
├─ [ ] 为 adapters/tool 实现超时、取消、权限、审计的统一包装
├─ [ ] 为 memory/store.py 实现向量库 Adapter，并保留 MemoryService 单一入口
├─ [ ] 为 communicator/service.py 接入可靠消息总线 Adapter
├─ [ ] 为 adapters/retrieval_adapter.py 修复迁移中的旧 retrieval 引用
├─ [ ] 在网络可用后重新下载并校验 CrewAI、Mem0、Haystack、AutoGPT 源码
└─ [ ] 每次引入第三方代码时记录版本、许可证、NOTICE 与适配层入口
```
