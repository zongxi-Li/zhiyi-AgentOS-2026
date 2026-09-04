# 知弈 AgentOS 当前架构图

> 视角：一次 ACG 请求从输入、规划、执行到输出与审计的真实主链。
> 原则：`ExecutionRuntime` 是唯一执行真源；Identity V2 只做身份一致性、投影与查询。

```mermaid
flowchart TB
    U[用户]

    subgraph Product[产品接入层]
        FE[Vue 3 Milan 工作台<br/>frontend/]
        NG[Nginx<br/>静态资源与反向代理]
        BE[Spring Boot Gateway<br/>backend/<br/>鉴权、用户与业务 API]
        PG[(PostgreSQL<br/>用户与产品业务数据)]
    end

    subgraph App[Python 应用与领域装配层]
        API[FastAPI<br/>agent/app/main.py<br/>/ai/agentos/v2]
        COORD[RunExecutionCoordinator<br/>后台任务生命周期]
        WIRE[Composition Root<br/>agent/app/execution/wiring.py]
        PACKS[领域 Packs<br/>legal / programmer / education / writer]
        EXT[模型、工具、检索适配器<br/>LLM Gateway / Tool Runtime / RAG]
    end

    subgraph Kernel[WKN AgentOS 唯一执行内核 · agentOS/]
        RT[ExecutionRuntime<br/>唯一编排与执行真源]

        subgraph Plan[准备阶段]
            PLANNER[Planner<br/>意图与能力规划]
            BLUEPRINT[ACG Blueprint<br/>有类型节点与边]
            COMPILER[ACGGraphCompiler<br/>冻结 Package、合同与 Binding]
        end

        subgraph Execute[执行阶段]
            GRAPH[ACGExecutionGraph<br/>就绪集、并行超步、条件控制]
            SCHED[Scheduler + Resource<br/>健康过滤、评分、Redis Lease]
            NODE[ACGNodeRunner<br/>Context → Agent → Audit → Commit]
        end

        subgraph Govern[贯穿执行的治理能力]
            COMM[Communication Broker<br/>字段白名单、ContextPack、熵预算]
            MEM[Memory<br/>受控召回与写入]
            AUDIT[Audit / Review<br/>证据、策略、人工屏障]
            RECOVERY[Recovery<br/>Checkpoint、Failure、GraphPatch]
        end
    end

    subgraph Truth[持久化与查询]
        WSTORE[(Workflow Store<br/>Mission / Run / Step)]
        CSTORE[(Checkpoint Store)]
        VSTORE[(Execution Value Store<br/>正文与 outputRef)]
        MSTORE[(Memory Store)]
        PSTORE[(Provenance Store)]
        DSTORE[(Decision Store)]
        IDV2[(Identity V2<br/>Mission / TaskPlan / Blueprint / Run / Attempt<br/>查询投影，不执行节点)]
        REDIS[(Redis<br/>资源租约与 Provider 状态)]
    end

    U --> FE --> NG --> BE --> API
    BE --> PG
    API --> COORD --> RT
    WIRE -. 启动装配 .-> API
    WIRE -. 注册 .-> PACKS
    WIRE -. 注入 .-> EXT

    RT --> PLANNER --> BLUEPRINT --> COMPILER --> GRAPH
    GRAPH --> SCHED --> NODE
    NODE --> PACKS
    NODE --> EXT

    GRAPH <--> COMM
    NODE <--> COMM
    NODE <--> MEM
    NODE --> AUDIT
    GRAPH <--> RECOVERY
    SCHED <--> REDIS

    RT <--> WSTORE
    RT <--> CSTORE
    NODE <--> VSTORE
    MEM <--> MSTORE
    COMM <--> PSTORE
    AUDIT <--> DSTORE
    RT -- 生命周期事件 --> IDV2

    IDV2 -. V2 查询 .-> API
    WSTORE -. 运行状态 .-> API
    VSTORE -. outputRef 解引用 .-> API
    API --> BE --> FE --> U

    classDef core fill:#eef2ff,stroke:#6366f1,stroke-width:2px,color:#171738;
    classDef projection fill:#f5f3ff,stroke:#8b5cf6,color:#30255f;
    classDef store fill:#f8fafc,stroke:#94a3b8,color:#27364a;
    classDef product fill:#f0fdf4,stroke:#4f8f70,color:#173b2b;
    class RT,GRAPH,NODE core;
    class IDV2 projection;
    class WSTORE,CSTORE,VSTORE,MSTORE,PSTORE,DSTORE,REDIS,PG store;
    class FE,NG,BE product;
```

## 阅读顺序

1. 用户请求经 Vue、Nginx、Spring Gateway 到达 FastAPI。
2. FastAPI 的 Coordinator 只管理异步任务生命周期，不承担图执行语义。
3. 唯一的 `ExecutionRuntime` 创建或读取 Mission/Run，调用 Planner 形成 Blueprint。
4. Compiler 将 Blueprint 冻结为可执行 Package；ExecutionGraph 决定就绪集与控制流。
5. Scheduler 分配资源和租约，NodeRunner 装配最小 ContextPack、调用 Agent、审计并提交引用。
6. Workflow、Checkpoint、正文、Memory、Provenance、Decision 分开持久化。
7. Identity V2 消费生命周期事件并形成稳定查询投影，但绝不调度或执行节点。
8. 前端查询 Run、图、Trace、血缘和 outputRef，形成最终可视化闭环。

## 不能混淆的边界

- `frontend/`：展示和交互，不推断运行真相。
- `backend/`：产品网关、鉴权和业务数据，不执行 ACG。
- `agent/`：FastAPI 应用、依赖装配和领域 Pack，不应复制内核算法。
- `agentOS/`：规划、调度、图执行、通信、记忆、审计与恢复的唯一核心。
- `agentOS/src/runtime/v2/`：身份生命周期和查询投影，不是 V2 执行器。
- `agentOS/drafts/legacy_execution/`：历史参考，不属于生产调用链。
