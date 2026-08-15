# AgentOS 后续实现 TODO

当前实现盘点见 `docs/current_implementation_review.md`。本清单只记录当前结构修复后仍需跨模块决策或实现的工作；每项均可独立验收。标记“可迁移”的项目仅授权调研和适配设计，**不授权直接复制第三方代码**。

## P0：恢复可作为基线的测试矩阵

- **现状：** 当前 `tests/support/` 的 5 个测试可通过，但工作区中有大量已删除且未提交的历史测试，无法判定各部件的完整回归状态。
- **边界：** 先确认这些删除是有意的架构迁移还是意外工作区状态；保留的合同、运行时、恢复、资源和规划测试须重新收敛到当前目录结构，不能只依赖两份 support 回归测试。
- **验收：** 定义并运行一份不依赖历史导入路径的测试矩阵；每个运行时关键路径至少覆盖成功、终态保护、恢复和插件范围失败；CI 命令和依赖清单可在干净环境复现。

## P0：收敛 ACG 与跨部件依赖

- **现状：** `support.acg.models` 同时承载共享模型、图校验、规划辅助算法和内置能力目录；planner、runtime、tools 与 recovery 都直接依赖它。recovery 还直接依赖 executor 的内部模块。
- **边界：** 新建 `contracts/acg.py` 承载纯模型、枚举和 JSON 兼容合同；将校验、升格、能力目录和意图语义画像拆入 planner；为 executor/recovery 交互建立公开合同或门面。保留 `support.acg` 兼容重导出，直到所有消费者完成迁移。
- **依赖：** 先补导入边界、模型序列化和运行时恢复的回归测试，避免将结构迁移与行为变化混在一起。
- **验收：** `support/acg/models.py` 不再承载算法或静态能力清单；新代码不从 support 导入跨部件合同；recovery 不导入 executor 的内部实现模块；兼容入口有弃用期与迁移说明。

## P1：为 WorkflowStore 建立完整适配器契约测试

- **边界：** 补齐 Memory/SQLite 在任务存在性、终态覆盖、幂等键“最新”定义、状态一致性校验、分页排序和删除孤立任务上的共同测试。
- **依赖：** 需要产品侧确认幂等键查询应按 `created_at` 还是 `updated_at` 选择最新运行；确认后两实现使用同一策略。
- **验收：** 两个适配器运行同一测试矩阵且结果一致；内存实现不再允许 SQLite 会拒绝的非法运行快照。

## P2：将 Pack 加载从 support 数据层移出

- **边界：** `PackManifest` 作为可序列化清单迁入 `contracts/plugin.py`；`register_installed_packs` 迁入运行时启动或插件适配层，并禁止直接修改全局 `sys.path`。
- **依赖：** 需要确定插件隔离方式（安装包、受控 importlib spec 或进程隔离）及失败回滚策略。
- **验收：** 清单解析不产生副作用；插件加载失败不会留下半注册的 Agent、Workflow 或 Capability；启动顺序可被独立测试。

## P2：完成 Skill Registry 或移除占位模块

- **边界：** 决定技能是通过 Pack 贡献统一注册，还是保留独立 `SkillRegistry`。
- **依赖：** 若保留，需先定义 `SkillRequest`、`SkillResult` 与 CapabilityManifest 的映射规则。
- **验收：** `support/skills/registry.py` 要么提供可测试的注册、作用域和解析行为，要么被删除且无引用残留。

## P1：实现统一能力注册表，并接入运行时装配

- **现状：** `ModelCompatibilityRegistry`、`AgentArchitectureRegistry` 与 `SkillToolCompatibilityRegistry` 只有 Protocol 和会抛出 `NotImplementedError` 的门面；`contracts/capability.py` 尚未被 `WorkflowRuntime` 消费。
- **边界：** 先实现无网络、副作用隔离的内存注册表：manifest 合法性、能力类别匹配、版本/命名空间冲突、确定性解析和健康状态投影。随后仅在 `runtime/bootstrap.py` 装配 registry；具体 SDK 留在 adapters 的 provider 实现中。
- **依赖：** 需先确定 capability ID、版本协商和“同一模型多实现”选择策略；不得把供应商 SDK 对象放入 contracts。
- **验收：** 三个 registry 使用同一类测试矩阵验证重复注册、错误类别、版本回退和不可解析能力；runtime 可通过公开依赖注入拿到 registry，且未配置外部 SDK 时保持可启动。

## P1：建立可演化的轨迹闭环（当前仅合同与门面）

- **现状：** `contracts/evolution.py`、`SkillEvolutionService` 和 `GraphEvolutionService` 已建立，但所有服务方法都是显式 TODO；执行器和审计器没有输出统一 `Trajectory`，也没有提案仓库。
- **边界：** 先从 executor/auditor 的已有 Trace 投影只读 `Trajectory`；实现确定性评分和候选/图变更提案，不允许这些服务直接写入技能库或运行中 RuntimeGraph。审核通过后再通过独立、带版本 CAS 的仓库持久化。
- **依赖：** 明确成功、效率、新颖度和质量的可复现计算口径，并先完成审核令牌、图版本及 recovery `GraphPatch` 的隔离规则。
- **验收：** 给定同一 Trace 输入，生成的轨迹、评分与提案稳定可复现；未审核提案不能修改技能或图；批准后的版本冲突可检测并可回滚。

## P1：可迁移——借鉴 LangGraph 的检查点与中断续跑语义

- **来源：** `references/open-source/langchain-ai-langgraph-d56666f/`，重点为 `libs/checkpoint/langgraph/checkpoint/base/`、`memory/`，以及 SQLite/Postgres 的一致性测试；需复核其 MIT 许可证和每个目标子包的 LICENSE。
- **落点：** `components/recovery/checkpoint.py`、`components/auditor/governance/checkpoint.py`、`support/stores/`。
- **说明：** 可迁移的是 checkpoint 元数据、版本/CAS、序列化与 conformance-test 思路；不引入 LangGraph StateGraph/Pregel 来接管现有 executor，避免双图运行时。
- **验收：** AgentOS 检查点具备版本、原子 compare-and-set、恢复读取和终态保护；Memory/SQLite 的同一组契约测试全部通过；若复制任何源码，新增许可证/NOTICE 记录和上游提交号。

## P1：可迁移——借鉴 OpenHands 的 Action/Observation 与工具事件边界

- **来源：** `references/open-source/OpenHands-OpenHands-e8e6f45/`；代码级复用前需锁定具体模块和复核 MIT 许可证。
- **落点：** `components/executor/dispatcher.py`、`components/auditor/governance/trace.py`、未来的 `adapters/tool/`。
- **说明：** 先在 AgentOS 合同中建立 Action、Observation、工具调用 ID、时间、取消与审计关联，再由 Adapter 处理沙箱、权限和外部副作用；不要嵌入 OpenHands 平台或绕过 Trace。
- **验收：** 一次工具调用可在 Trace 中完整关联请求、结果/错误、取消和资源限制；超时或取消不会让迟到结果越过 executor 屏障；任何源码搬运都有版本与声明记录。

## P2：可迁移——以 Adapter 方式接入 Mem0/Haystack 的记忆与检索能力

- **来源：** `references/open-source/mem0ai-mem0-4debc58/` 与后续经完整校验的 Haystack 快照；复用前必须复核 Apache-2.0 的 LICENSE、NOTICE 及子依赖。
- **落点：** `components/memory/store.py`、`components/memory/retrieval.py`、`adapters/retrieval_adapter.py`。
- **说明：** 可借鉴抽取、合并、向量召回、重排和 DocumentStore/ Retriever Adapter 模式；MemoryService 保持唯一读写入口，外部存储不得绕过准入、权限、审计或生命周期。
- **验收：** 向量 Adapter 的读写都经 MemoryService；权限过滤先于召回结果返回；可复现的 recall/rerank 测试覆盖冲突保留、预算裁剪和供应商故障降级；第三方归属文件齐全。

## P2：仅借鉴建模——CrewAI、AutoGen 与 AutoGPT

- **边界：** CrewAI 仅参考角色—任务—依赖/Flow 表达；AutoGen 仅参考消息拓扑和终止条件；AutoGPT 仅参考工作流可视化与扩展体验。
- **说明：** 这三者不得接管 AgentOS runtime；AutoGen 与 AutoGPT 当前不进入代码搬运清单，需在每个目标子模块层面完成许可证与发布义务审查后才可改变此结论。
- **验收：** 每一项采用均以 AgentOS contracts 为唯一边界，并有独立 ADR/设计记录说明未形成双编排器或外部对象泄漏。
