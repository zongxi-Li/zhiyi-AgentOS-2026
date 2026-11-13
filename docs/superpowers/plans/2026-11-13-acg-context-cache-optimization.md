# ACG 上下文与模型缓存优化计划

日期：2026-11-13。状态：阶段一、二已实施；阶段三已完成无损重复内容投影、可配置请求预算及现有 Workset 范围/覆盖修复，自动章节规划尚待实施；阶段四由实测触发。

## 目标与基线

降低 ACG 的无效模型输入与未命中 Token，在交付完整、权限和执行语义正确的前提下改善缓存复用。缓存命中率、通信节省率、记忆召回率分别统计。

本次只读复核 Mission `mission_a0bb01491a81` 的运行记录：

- Run：`run_4157e2ae795b`，状态 completed。
- 执行模型调用 27 次，输入 486,142 Token，缓存读取 63,360 Token，加权命中率 13.03%。这些数字不包含未纳入该 Run 执行 trace 的规划等调用。
- 27 次调用的 stablePrefixHash 相同；模板和 Schema 分别有 8 种。模板差异不能直接认定为公共前缀失效。
- API 设计节点上游可获取/实际投递均为 7,771 个估算 Token；实际模型输入 17,639 Token，缓存读取 2,176 Token。
- 最终交付汇总输入 107,820 Token，架构评审 57,625 Token，最终验收 50,843 Token。三者占总输入 44.49%。

原 Run 作为只读基线。新策略仅用于新编译并激活的执行包，不改历史冻结合同，不自动重放该任务。

## 已有能力与明确问题

1. `adapters/execution_prefix.py` 已为原生 DeepSeek 执行请求生成四段消息：公共 system、共享任务 user、能力与输出合同 system、节点输入 user。`openai_runtime.py` 将 Schema 放在第三段。保留此布局及其信任边界。
2. `tests/adapters/test_execution_prefix.py` 已覆盖跨能力公共前缀、无损重构、信任标签和续写请求。测试存在不代表本次已运行。
3. `planner/lowering_input.py:lowering_step_from_task()` 默认把每个依赖的全部顶层输出字段写入 input.from；初始和增量通信规则也默认允许全部输出字段。权限可控，但默认消费范围偏宽。
4. 默认 lowering 的记忆 tokenBudget 为 None；Broker 预读使用 max_tokens=None。Manifest 可以有限额，但这些入口没有统一的完整请求预算分配。
5. `adapters/model/prompt_context.py` 已消除扁平 data 与 sourceData 的大块完全镜像，不应重复实现。不同来源、不同字段内部的长文仍会保留。
6. `native_capabilities.py` 的成果输出同时要求 deliverable、final_answer、verification、artifact；正文可能在多个表达中出现。不能假定它们完全等价后直接删除。
7. CommunicationReader 已支持分页，NativeGeneralAgent 已有 Workset 的 map/reduce。优先接入这些机制，避免建立第二套内容或执行状态。
8. API 的缓存用量投影未直接识别 prompt_cache_hit_tokens。本次记录有 prompt_tokens_details.cached_tokens，因此当前任务的缓存读取未被漏计；仅提供原生字段的响应存在兼容缺口。

## 阶段一：完善计量和请求诊断

涉及：`adapters/model_runtime.py`、`adapters/openai_runtime.py`、`adapters/model_adapter.py`、`app/api/agentos_v2.py`。

- 在实际发送边界记录布局版本、最终消息分段长度和摘要，识别公共段、策略/Schema 段、节点数据段。保留现有模板、Schema、公共前缀标识。
- 摘要和长度不得复制正文、密钥、完整材料；明确长度估算与供应商 Token 实测的区别。只有同源 tokenizer 或供应商数据支持时才报告精确前缀 Token 数。
- 按模型、布局版本、公共前缀和能力聚合缓存读取、输入、未命中、调用数；保留整个 Run 的加权比率。
- 兼容 DeepSeek 原生缓存字段，防止多个别名重复计数；缺少缓存用量与明确零命中应能区分。
- 此阶段不更改请求正文和消息顺序。

验收：缓存别名和缺失场景正确；stream/non-stream/续写均能定位实际请求；诊断不改变请求内容；不把本次 13.03% 错报为统计 bug。

## 阶段二：收紧默认上下文消费

涉及：`planner/lowering_input.py`、`planner/semantic_patch_planning.py`、`support/acg/capabilities.py`、`support/acg/native_capabilities.py`、通信 Manifest 编译处。

- 从消费方合同及任务依赖语义确定最小输入字段。无法确定时保留兼容行为并记录原因，不静默删掉数据。
- 区分 allowedFields（可读取权限）和 prefetch（首次预读集合）；两个集合由同一编译规则生成并校验，prefetch 必须为授权子集。
- 先对 verification、artifact_generation 明确输入策略，消除默认把所有交付表达同时预读的行为。评审需要检查的原始正文必须仍可受控读取。
- 新规则写入版本化的编译产物，保持初始编译和语义补丁一致；不在运行中修改冻结权限。
- 给记忆召回配置有界预算，但把它作为补充控制，不能认定其是本次大输入的主要来源。

验收：API 设计仍能区分两个上游 solution_design；来源同名字段不丢失；必需字段、约束、验收条件和证据均可追溯；旧执行包按原规则恢复。

## 阶段三：治理长文与重复交付表达

涉及：`adapters/model/prompt_context.py`、`support/acg/native_capabilities.py`、`components/content`、`components/communicator/broker.py`、`adapters/model/native.py`。

- 先分析 artifact.content、deliverable.sections、final_answer 的完全重复部分；通过内容摘要与内联引用复用相同内容，保留不同内容及来源。扩展现有投影，避免另建压缩器。
- 明确主交付表示及其他显示表示的关系。能确定性生成的显示内容逐步由渲染生成；输出合同变更必须版本化，并检查 UI、审核、恢复和下游消费兼容性。
- 对不能放入合理预算的正文，使用现有 Content Manifest、Workset 和受控分页。引用必须在当前授权上下文中可解析，不能只交给模型一个无法读取的 ID。
- 最终汇总、架构评审、验收按章节或检查项分片，再归并。每个分片保留覆盖清单、来源和未决项，不用摘要替代必须审查的证据。
- 把系统提示、公共任务、节点输入、记忆、工具观察以及输出预留纳入节点请求预算；超过预算选择分页或分解，不静默截断。分解涉及执行图变化时走现有规划/激活权威。

验收：逐项证明源章节和检查项被覆盖；工具/材料中嵌入指令仍为数据；不可因分片丢掉否定约束；减少大输入不能依靠降低交付完整性。

## 阶段四：有证据后优化剩余前缀

涉及：`adapters/execution_prefix.py`、`adapters/prompt_runtime.py`、`adapters/openai_runtime.py`。

- 根据阶段一数据寻找同组请求的首个非必要变化，修复不稳定顺序、渲染版本或动态元数据污染。当前已有四段布局不做无依据重写。
- Schema 和工具定义采用稳定序列化；保持数组的业务顺序，不为缓存改变执行含义。
- 不把不同模型/权限范围的请求混为一组，不扩大工具许可，不串行化全部 DAG，不用隐藏预热调用制造更高命中率。
- 分别统计首次构建、后续复用和并行调用；不承诺固定命中率，也不以 stablePrefixHash 相同推断供应商缓存一定可用。

## 验证与发布

1. 阶段一优先覆盖 `test_execution_prefix.py`、用量投影及流式/续写合同测试。
2. 阶段二覆盖初始/增量 lowering、通信权限、prefetch 和冻结包恢复。
3. 阶段三覆盖重复内容无损投影、Workset 分片覆盖、评审证据及完整交付。
4. 使用相同材料和验收标准建立新 Run 对照。外部模型调用的费用、模型版本、调用时序、是否预热均显式记录。
5. 比较总输入、未命中 Token、输出和修复调用数、耗时、费用及交付完整性。分片新增调用全部计入，不只挑缓存更好的调用。
6. 通信 Token 是估算值；增加完整模型输入与分段统计，避免将 ContextPack 的节省率解释为缓存命中率。

建议首先交付阶段一与阶段二。阶段三优先处理本次三个超大节点，阶段四由实测问题触发。

阶段一、二的实现、验证和生效边界见 [实施报告](../reports/2026-11-13-acg-context-cache-stage12-report.md)。尚未调用外部模型重放任务。

阶段三本批实现及对原 Run 的只读投影对照见 [阶段三实施报告](../reports/2026-11-13-acg-context-cache-stage3-report.md)。当前请求格式支持完全相同的长字符串、对象和数组引用；请求预算须由能力目录声明并进入新编译包，不向历史包追加默认硬限。上游交付物自动转为按章节 Workset 的规划/激活链路仍待实现，不将本批标记为整个阶段三完成。
