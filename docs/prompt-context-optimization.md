# 任务上下文与缓存优化

本次变更只调整模型请求的渲染，不迁移或改写已有 ContextPack、结果、通信账本和证据存储。

## 请求行为

1. `NativeGeneralAgent` 将步骤已有的 `from` / `prefetch` 字段需求交给提示词构造器。只对明确声明的生产步骤裁剪字段；未声明的材料和本地计算保留。空字段列表继续沿用 Broker 的“全部已授权字段”语义。没有引入自动摘要或正文截断。
2. `project_prompt_context()` 用规范 JSON 比较完整字段值。较大的 `upstreamOutputs` 镜像用 `upstreamOutputRefs` 替代，正文保留在同一请求的 `sourceData.content.contextSources[sourceId][field]` 中。小值继续内联，避免引用开销大于正文。不同生产步骤的同名但不同值均保留。
3. 别名通道仍为 `agent_generated`，目标通道仍为 `external_untrusted`；系统合同明确禁止别名提升目标的信任等级。别名只表示请求内的数据关系，不触发外部工具读取或证据验证。
4. 公共系统合同放在角色和能力策略之前；请求中稳定的 mission / taskSources 放在变化的步骤信息之前。对象键规范化，数组顺序保留。能力策略和传输层 Schema 校验继续留在系统层。

版本更新：`native-capability.v4`、`verification.v3`、`artifact-synthesis.v4`、`execution-request.v2`、`prompt-runtime-renderer.v2`、`agentos-kernel.v2`。

## 已验证的收益

对 `run_ba8996ca8b6c` 的七份已保存上下文进行只读比较，仅计算 upstreamOutputs / sourceData 及新增别名通道的规范 JSON 字符量，包含引用开销：

| 指标 | 结果 |
| --- | ---: |
| 优化前 | 78,657 字符 |
| 优化后 | 42,671 字符 |
| 减少 | 35,986 字符 / 45.75% |
| 原字段及生产步骤记录还原 | 七份全部一致 |

这个比例不是整个模型请求、计费 Token、费用或缓存命中率的降幅。此只读审计不重新执行任务，也不修改历史统计；后续真实复测见下方报告。

可复查命令（当前 Docker 开发服务）：

```powershell
Get-Content ops/scripts/audit_prompt_context.py -Raw -Encoding UTF8 |
  docker exec -i kinlin-win-p1-001-ai-service-1 python - --database /app/data/agentos/execution_values.sqlite3 --run-id run_ba8996ca8b6c
```

## 验证与后续验收

后续已实现字段级修复与原消息前缀复用，见 [实现与实测报告](field-repair-validation-20261005.md)。完整 Run 和受控缺字段回放分别计量，不能将预热回放命中率当作完整任务收益。

- AgentOS 适配器、通信和动态读取回归：162 项通过（含复测发现的修复调用计量测试）。
- Agent 模型运行时、网关审计边界和规划器模型边界：14 项通过；一条已有 Pydantic 配置弃用警告。
- 真实 DeepSeek Flash 小样本：正确读取引用，区分两个生产步骤的 `analysis`，保留 `not_verified` 状态。样本总用量 1,312 Token；此项证明模型理解引用，不证明缓存命中率提升。
- 2026-10-05 已完成真实后继 Run 复测，详见 [复测报告](prompt-context-retest-20261005.md)：缓存命中率从 6.46% 提升至 34.22%，未命中输入减少 23.29%；一次契约修复导致任务总 Token 增加 1.68%。此为单次观察，包含缓存预热影响。历史 Run 的 6.5% 不会因渲染变更而重新计算。

能力策略和 Schema 仍会使不同能力的完整 system 消息不同，因此目前不承诺跨能力复用长材料缓存。公共前缀优化主要稳定共享系统规则及同能力请求；若后续要把长材料共享到不同能力的请求前缀，需要单独设计消息分层并验证供应商兼容性与指令边界。
