# Gitee 模型运行时迁移评估

> 创建（Git）：2026-08-20T18:47:17+08:00，For N
> 最近一次 Git 修改：2026-08-20T18:47:17+08:00，For N

## 提交拓扑

- 来源：`origin/master` 的 `da04b7a feat(agentos): add guarded model runtime setup`
- 目标基线：`027e862`（General Golden Path 完成后的隔离分支）
- 共同祖先：`fc8eee0`
- 当前 `master` 相对 Gitee 为 18 个本地提交、1 个远端提交；两者是分叉关系，不能快进推送。

直接合并会把来源分支缺少的 Resource、Scheduler、Memory、Recovery、Evolution 与
Golden Path 变化一起带入三方合并，风险远高于该提交本身的 17 个文件范围。因此本次
只按能力合同做语义迁移，不合并或 cherry-pick 来源提交。

## 能力判定

| 来源能力 | 当前主线状态 | 迁移决定 | 原因 |
| --- | --- | --- | --- |
| OpenAI 兼容 SSE 传输 | 模型适配器已有 `astream`，HTTP 传输缺实现 | 迁移 | 补齐真实传输链，保持请求正文不入状态 |
| 流式工具调用事件 | 合同只支持文本与完成事件 | 迁移 | 仅作会话内投影，不进入 checkpoint 或 Trace |
| 工具流式执行 | 无入口 | 修正后迁移 | 来源实现未让保护层覆盖完整流的并发与总超时 |
| `FrameworkAgent` | 只有框架 registry，无 `BaseAgent` 桥接 | 迁移 | 外部框架仍被限制为现有 ACG 的单节点执行者 |
| `ApplicationSetup` | Runtime 已有模型 registry，但应用未装配环境模型 | 修正后迁移 | 来源默认新建 registry，未与真实 WorkflowRuntime 接通 |
| 新 Runtime / Scheduler / Memory / Evolution | 来源未新增 | 不涉及 | 保持现有单一实现 |

## 接线约束

AI Service composition root 必须把 `WorkflowRuntime.model_registry` 注入
`ApplicationSetup`，并在 FastAPI lifespan 内启动和关闭。`AGENTOS_MODELS` 只登记
冻结模型绑定可解析的适配器，不替换现有默认结构化生成网关，也不创建第二套执行链。

`FrameworkAgent` 只提供可显式注册的桥接类型；本次不自动复制任何领域 Agent，
也不让外部框架接管 ACG、审核、记忆、检查点或调度。

## 验证边界

迁移测试必须覆盖同一 registry 身份、真实本地 HTTP 的 429 候选切换、SSE 关闭、
密钥轮换、工具流授权与超时、FrameworkAgent 取消传播，以及既有 AgentOS/AI Service
完整回归。测试端点只用于传输合同验证，不生成 Golden Run 或业务展示数据。
