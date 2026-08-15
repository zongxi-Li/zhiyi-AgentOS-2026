# ACG 通信改进设计

## 目标

将 ACG 的通信从“由编译期精确字段契约决定全部内容”调整为“规划期控制拓扑与模式，运行期通过受控 Broker 按需读取”。`STRICT_CONTRACT` 继续用于已知的高确定性结构化链路，但不再成为开放任务能否执行的前提。

系统仍然禁止在执行 State、checkpoint、Trace 中保存输出、上下文、记忆、提示词、工具参数或模型响应正文；这些位置只能保存摘要、统计数据与受控引用。

## 当前交付

截至本轮，`STRICT_CONTRACT` 的真实执行路径已经接入受控 Broker，而不是仅停留在独立组件测试：

- `ACGGraphCompiler` 以 `runId` 编译内部 `CommunicationManifest`；依赖边成为唯一可读拓扑边。未精确声明 `inputSpec.from` 时，生产步骤的公开 `outputSpec.properties` 只作为字段读取上界，不被当作编译期必填 slot 契约。
- `WorkflowRuntime` 为每次图执行创建共享 Broker。节点读取上游输出必须经过 Broker；运行 State 与 SQLite checkpoint 只保存 `communicationUsage` 的 `run`、`steps`、`channels` 三类整数计数。
- Broker 的读取结果会回写既有消费/交互血缘账本，并投影为 `data_consumed` Trace。Trace 载荷严格限定为 run、生产/消费步骤、输出引用、字段名、Token 计数和逻辑通道，不记录读取理由或正文。
- 恢复时 Broker 从 checkpoint 的预算计数继续扣减；空图和根节点也规范化为零值计数，避免提交重放生成不同 checkpoint 摘要或重复保存版本。
- `EVENT` 仍只传递受控事件引用，`BLACKBOARD` 与 `DEBATE` 仍由编译器明确拒绝。修订去重、事件变化发布、受保护工作记忆与受治理辩论子图尚未实现，不能作为可用能力宣传。

本轮验证：`python -m compileall -q src`、`pytest -q`（151 项通过）及 `git diff --check`。

## 总体结构

每个 ACG Blueprint 新增内部 `CommunicationManifest`，由编译器生成而不泄漏到公开 contracts：

- 节点及依赖边：仅为真实数据依赖建立通信边，无边即不可读；
- 节点通信模式：`STRICT_CONTRACT`、`EVENT`，后续的 `BLACKBOARD`、`DEBATE`；
- 读取范围：允许的上游步骤、字段白名单或“仅摘要”范围；
- 预算：运行、步骤、通道三级 Token/熵预算；
- 权限：读取者、写入者、审核要求与保留期。

`CommunicationBroker` 是正文读取的唯一入口。节点首先只获得上游摘要、引用和 Manifest；需要正文时必须调用类似下列的请求：

```python
await broker.read_reference(
    run_id=run_id,
    consumer_step_id=step_id,
    output_ref=output_ref,
    requested_fields=["marketSize", "competitors"],
    max_tokens=800,
    reason="estimate market opportunity",
)
```

Broker 依次校验引用归属、拓扑边、读取权限、字段或范围、剩余预算、血缘完整性和当前审计状态。成功时只返回裁剪后的 `ContextPack`；失败时返回稳定错误，不向节点暴露未授权正文。每次读取写入不含正文的血缘和 Trace 投影。

## 规划期规则

规划器只承担两项责任：

1. 按步骤的真实数据依赖建立通信拓扑；没有依赖的步骤没有通信边，因此不可读取彼此输出。
2. 为步骤选择通信模式：主干且结构稳定的链路优先 `STRICT_CONTRACT`；状态信号使用 `EVENT`；探索型协作用后续 `BLACKBOARD`；受限决策协调用后续 `DEBATE`。

`STRICT_CONTRACT` 对声明字段执行现有合同校验；未能精确声明字段的开放任务可采用“摘要加受控引用”运行时读取，不允许把所有上游输出直接注入 Agent。`BLACKBOARD`、`DEBATE` 在相应实现完成前继续由编译器明确拒绝，禁止静默降级。

## 正文、摘要与大对象

输出正文继续存放在 `ExecutionValueStore`，引用由既有 run/step 守卫绑定。第一期大对象不额外引入文件系统依赖：Value Store 增加大小、摘要、内容修订号等元数据，Broker 默认返回摘要并按预算裁剪读取。后续若需要跨进程大型二进制对象，再增加独立 `ArtifactStore`；它也只能暴露带权限的引用。

压缩策略按从轻到重的顺序执行：字段裁剪、重用已有摘要、传递同修订号的引用、受审计压缩、请求人工审核或重规划，最后抛出 `EntropyBudgetExceededError`。压缩过程必须保留来源引用和修订信息，不能把正文写入 Trace。

## 预算与修订

预算采用 `runBudget -> stepBudget -> channelBudget` 的层级。Token 估算采用保守、可替换的纯本地计算；实际供应商 usage 仅作为审计统计，不能突破预算。每次成功读取或发布都记录不含正文的消耗量、修订号和降级原因。

每份输出保存整体内容哈希和修订号。第一期差异通信仅作“同修订去重”：修订未变时不重新传正文，只返回既有引用或摘要；字段级 patch 和文本 diff 后续增加。`EVENT` 仅在修订号、运行状态、审计决定或预算风险发生变化时发布；状态未变时不得产生重复事件。

## BLACKBOARD 与 DEBATE

`BLACKBOARD` 将是受保护的工作记忆引用仓库，不是 Python 共享字典。每个 topic 必须声明 run 作用域、读写步骤、字段白名单、预算和保留期；读写都经过 Broker、血缘、Trace、审计和恢复守卫。

`DEBATE` 只允许受治理的有限子图：Blueprint 明确参与者、最大轮数、聚合节点、终止条件和审核点。每轮都是普通可 checkpoint 的 ACG 节点，轮次正文仍由引用仓库存放。轮数耗尽、高风险结果或审核规则命中时必须中断，不允许开放式循环。

## 安全与清理

外部模型和工具调用通过保护包装器接收同一 `commitId`，统一执行超时、临时故障重试、限流和安全错误映射。孤儿清理器只延迟清理没有被节点提交、运行 State、checkpoint 或待审核记忆引用的输出和 ContextPack；绝不删除审计决定、正式记忆、血缘账本、提交记录或 checkpoint。

删除现有代码必须同时满足：`src/`、`service/`、`tests/`、`docs/` 无静态引用，不是已声明的未来边界，并通过完整测试与导入边界检查。本轮不因目录整洁删除仍承担兼容、恢复或审计职责的代码。

## 实施顺序

1. 模型和工具外部副作用保护层；
2. 孤儿引用延迟清理；
3. 五阶段故障注入恢复演练；
4. Manifest、Broker 与三级预算；
5. 修订去重和 EVENT 变化触发；
6. 受保护 BLACKBOARD；
7. 受治理 DEBATE 子图。
