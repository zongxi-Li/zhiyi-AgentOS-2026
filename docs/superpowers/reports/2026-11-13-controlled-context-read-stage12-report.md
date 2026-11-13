# 受控上下文补读与预算：阶段一、二实施记录

## 实现原则

下游需要的是完成当前步骤所需的事实，而不是访问整个运行状态的权限。新增能力只把现有 CommunicationReader 接入模型工具循环，权限仍由冻结通信 Manifest 与 Broker 校验；正文仍在既有 Value Store 中，模型决策复用既有工具 WAL。没有新增权限权威、执行状态机或存储系统。

## 已实现

原生能力的新执行包冻结 `contextPolicy.supplementalReadBudget`，并提供三个只读工具：

- `context.list_sources`：列出当前节点获准读取的生产步骤、字段、是否存在及估算大小，不返回正文和 outputRef。
- `context.read`：按生产步骤和字段读取，经 Broker 验证 Run、引用归属、拓扑、字段和预算。
- `context.read_page`：按字段分页，返回下一页游标和当前范围。尾页不代表已经阅读前面的页，提示合同要求按需遍历并明确报告证据缺口。

模型只支持 Function Calling 时才进入现有工具循环；无需配置 Hands，也不会因开启补读扩大文件、Shell 或外部工具权限。工具名冲突由已有唯一性校验拒绝。

策略默认单次最多 4096、默认页 1024、节点累计补读最多 16384 个估算 Token；可通过原生能力的 ContextConsumptionPolicy 配置。初始与增量 lowering 使用相同策略冻结路径。旧执行包缺少该策略时不注册补读工具，首次预读字段保持原逻辑。

补读仍服从既有通信 Run、步骤、通道上限。新增累计补读额度与首次预读分开计量，避免把现有大额首次预读误判为补读超限。拒绝的读取不扣额度；预算数值禁止布尔值、零值及不一致的大小关系。

完整模型请求预算继续使用冻结的 `contextPolicy.requestBudget`，工具定义、工具结果、Schema、消息和输出预留均计入发送边界检查。测试覆盖补读后下一次模型请求超限，在发送前失败。**本次未替所有模型生成默认的完整请求总预算**：模型上下文容量和输出预留需由配置明确提供；未配置时仍报告 notConfigured，不能把补读额度误称为完整模型预算。

## 恢复与观测

- 首次预读和模型补读分别使用稳定操作键。通信使用快照新增操作指纹与累计补读数字；相同操作重放不重复扣额度，同键内容改变明确拒绝。
- 操作指纹覆盖正文、来源引用、字段和读取参数，快照只保存哈希而非正文。
- 原生工具循环在没有外部工具运行时，也能复用 Reader 所属 Value Store 的模型决策 WAL。SQLite 关闭、重开后，可以恢复模型工具决策而不再次请求模型。
- 模型补读在成功读取时登记既有来源账本；合法补读取得的证据引用继续参与原生输出引用处理。
- Trace 保留读取阶段、读取种类、字段、估算量、操作键与分页游标；成功和失败的上下文工具调用沿用工具执行记录。来源账本不包含正文和模型提供的读取理由。
- 分页的可获取量与投递量按当前页相等计入通信节省统计，原字段大小单独记录；不会把“尚未发送的后续页”反复计算成节省。

## 分页边界

修复原分页字符串按字符宽度选页而可能突破估算上限的问题，计入字段 JSON 信封开销，并验证超出范围的游标。字符串支持包含转义符和 Unicode 的完整还原。

对象和列表按完整条目分页。若一个嵌套条目本身超过预算，明确拒绝，不返回超限第一页或静默截断。此情况需调整冻结额度或使用既有 Workset 分片；任意深度的对象路径补读不在本次范围内。

## 验证

使用真实 NativeGeneralAgent、AgentToolSession、RegisteredModelRuntime、OpenAICompatibleRuntime、CommunicationBroker、ACGNodeRunner 和 SQLite Value Store；仅模型 HTTP 响应用测试传输替代，无收费请求。

新增测试覆盖：权限目录不泄露正文、越权来源和字段拒绝、超限不扣额度、Unicode/转义分页还原、嵌套超大条目拒绝、操作重放与冲突、旧执行包关闭工具、工具循环读取、原生节点血缘与状态隔离、完整模型请求预算、SQLite 重开后恢复、策略参数校验。

主回归命令在 `apps/agentOS` 运行，结果 193 passed：

```text
python -m pytest -q tests/adapters/test_context_read_tools.py tests/adapters/test_unified_tools.py tests/adapters/test_native_agent.py tests/adapters/test_request_budget.py tests/adapters/test_inline_content.py tests/adapters/test_prompt_context.py tests/adapters/test_execution_prefix.py tests/adapters/test_native_prompt_v2.py tests/components/communicator tests/components/planner/test_context_consumption_policy.py tests/components/planner/test_topology_compiler.py tests/components/executor/test_value_store.py tests/runtime/test_dynamic_reads.py
```

分页统计口径调整后，再次运行补读、通信器、动态读取、故障恢复及审核恢复回归：49 passed。两个测试集合有重叠，不将通过数相加。

## 生效条件和下一步

本次没有重启服务、修改历史 Run 或调用付费模型。后端加载新代码后，新编译的原生执行包可获得补读工具。旧执行包不会被回写。

首次预读没有收紧，也没有启用自动摘要。本次证明补读、权限、计量、幂等和节点提交链路可工作，不证明生产模型会主动合理分页，也不报告 Token、缓存命中或费用改善。下一步才是为核查节点收紧版本化预读策略，并用新 Run 验证验收覆盖、实际输入、补读次数和耗时。
