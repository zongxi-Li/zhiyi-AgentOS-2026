# src 源码分层

```text
src/
├─ contracts/      跨层、跨部件唯一共享的数据合同
├─ components/     业务部件层
│  ├─ task_manager/ planner/ resource/ scheduler/ executor/
│  └─ communicator/ memory/ auditor/ recovery/
├─ runtime/        薄编排与依赖生命周期
├─ adapters/       模型、工具、存储、远程 Agent 等外部适配
├─ tools/          ACG JSON 导出与 Mermaid / DOT 绘图工具
└─ support/        Agent、Pack、Skill、旧线性模型与工作流存储配套实现
```

依赖方向：`runtime → components → contracts`；`adapters` 只在明确的注入点实现外部能力；
`support` 不应成为新的跨部件数据合同来源。

> TODO：逐步把 support/domain 中与 contracts 重叠的任务、工作流模型归并为唯一合同，
> 并将 support/stores 的持久化 Interface 下沉到对应业务部件，消除历史双模型源。
