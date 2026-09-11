# Node/Agent Resource Ledger Migration Design

## Goal

把 AgentOS 资源器从旧的单张 `ResourceProfile/ResourceSnapshot` 账本迁移到 Node 与 Agent 两张主账本。迁移期以新 Node/Agent 账本作为唯一写入真源，旧 Resource 接口仅保留兼容门面；Runtime、调度、租约、心跳和远程执行全部切到新账本后，再删除旧表和兼容门面。

## Confirmed Migration Rule

新 Node/Agent 表是唯一写入真源。旧 `ResourceService`、`ResourceDirectory`、旧 API 响应和旧 `resourceId` 字段只作为兼容层存在，不再维护独立健康、容量、凭据或租约状态。

迁移期规则如下：

- 新节点登记写入 Node 表和节点凭据。
- 新 Agent 登记写入 Agent 表和 Agent 快照。
- 旧 Agent 类资源 ID 映射到 `agentId`。
- 旧 worker/model/tool/embedding/mcp 类资源 ID 映射到 `nodeId`。
- 历史旧表数据只做一次性导入或只读兼容投影；导入后以新表记录为准。
- 旧查询端点可以继续返回旧字段形状，但数据来自 Node/Agent 真源。
- 无法唯一映射的旧 `resourceId` 必须明确失败，不能猜测或回退到本地执行。

## Ledger Shape

逻辑主表保持两张：

- `nodes`：保存 `NodeProfile` 静态画像和当前 `NodeSnapshot` 动态快照。
- `agents`：保存 `AgentProfile` 静态画像和当前 `AgentSnapshot` 动态快照。

支撑状态使用独立表，不塞回旧资源表：

- `resource_credentials`：保存节点签名凭据的 ID、密文、摘要、owner scope 和版本。
- `resource_observation_nonces`：保存短期 nonce，用于防重放。
- `resource_leases` 或 Redis 等价键空间：保存 `agentId + nodeId` 绑定租约。

`NodeProfile` 需要显式支持 `modelIds`。模型能力不能只藏在 `metadata`，否则调度无法稳定验证模型约束，也无法给出可审计的失败原因。

## Composition Root

`apps/agent/app/execution/wiring.py` 默认注入新账本组件：

```text
SQLiteNodeStore
SQLiteAgentStore
NodeService
AgentService
AgentDirectory
TwoLayerSchedulerService
NodeExecutionAdapterFactory
```

旧兼容门面可以继续存在，但必须代理到新账本：

```text
LegacyResourceFacade -> NodeService / AgentService
LegacyDirectoryFacade -> AgentDirectory / AgentService
```

启动后，原生 Agent 和插件 Agent 通过 `AgentDirectory` 写入 Agent 表；远程节点通过 `/nodes/register` 写入 Node 表和节点凭据。

## Joint Scheduling

调度不再先独立选择 Agent、再独立选择 Node。新调度器必须枚举并筛选 `(Agent, Node)` 组合，只有组合整体合法才能返回。

硬约束如下：

- Agent 必须启用、健康可用、满足步骤要求的全部能力，并符合 `onlyIdle`。
- Node 必须启用，健康状态不能是 `stale` 或 `offline`，并且仍有可租用槽位。
- `AgentProfile.allowedNodeIds` 非空时，Node 必须在白名单内；为空表示允许所有符合其他条件的 Node。
- 模型要求为 `step.requiredModelIds ∪ agent.requiredModelIds`，Node 必须支持全部模型。
- 显存要求为 `max(step.minGpuMemoryMb, agent.requiredGpuMemoryMb)`。
- 隐私要求为步骤隐私等级与 Agent `minPrivacyLevel` 中更严格的一方，Node 必须达到该等级。
- Step 的 Node 类型、部署层、数据区、标签、延迟、成本和远程执行限制继续作用于 Node。
- owner scope 或绑定关系不一致时，组合淘汰。
- Agent 有白名单但白名单节点全不合格时，不能回退到其他节点。

排序规则必须确定：先硬过滤，再计算 Agent 成功率/能力得分、Node 负载/延迟/可靠性得分和组合总分；同分按 `agentId`、`nodeId` 升序。

调度结果升级为可审计配对：

```text
TwoLayerPlacement
  agentId
  nodeId
  agent
  node
  effectiveRequirements
  agentScore
  nodeScore
  pairScore
```

## Lease Model

`ResourceLease` 迁移为 `agentId + nodeId` 绑定租约，并保留 `resourceId` 兼容字段。新代码只使用 `(agentId, nodeId)` 参与容量占用、释放、续租和故障迁移判断。

Redis 键空间：

```text
agentos:lease:{leaseId}
agentos:pair:{agentId}:{nodeId}:leases
agentos:pair:{agentId}:{nodeId}:slots
agentos:lease-index
```

单次 Redis Lua/CAS 分配必须完成：

1. 清理已过期租约。
2. 检查同一 `leaseId` 是否已存在，保证重试幂等。
3. 汇总同一 `(agentId,nodeId)` 的活动槽位。
4. 检查 Node 容量和 Agent 并发上限。
5. `SET NX + TTL` 写租约主体。
6. 写索引、槽位和过期集合。
7. 任一步异常时不分配。

内存实现必须保持同样语义，作为单元测试和本地运行的确定性实现。旧调用只传 `resourceId` 时走兼容解析；无法唯一解析时拒绝。

## Node Observation Endpoint

新增 `/nodes/{id}/observation`，使用和旧 `/resources/{id}/observation` 同一 canonical HMAC 规则，但凭据来自 `NodeStore`。

请求头：

```text
X-Node-Credential-Id
X-Node-Timestamp
X-Node-Nonce
X-Node-Signature
```

签名文本：

```text
METHOD
PATH
TIMESTAMP
NONCE
SHA256(BODY)
```

服务端处理顺序：

1. 根据 `nodeId` 读取 Node 凭据。
2. 校验 credential id。
3. 校验 timestamp 在允许时间窗内。
4. 校验 HMAC。
5. 原子消费 nonce；重复 nonce 返回冲突。
6. 读取当前 Node 快照。
7. 要求 `observationSequence > current.observationSequence`，相等和更小都拒绝。
8. CAS 更新 Node 快照。
9. 同步更新 Node 健康投影，让调度立即看到一致状态。

该协议必须防止伪造节点、重放旧包、旧序号覆盖新状态，以及多个 AgentOS 进程互踩心跳。

## Runtime Migration

Runtime 迁移顺序：

1. `wiring.py` 注入持久化 Node/Agent Store，并让 Agent 注册写入 Agent 表。
2. Runtime 调度入口改为 `TwoLayerSchedulerService.schedule`，获得合法 `(agentId,nodeId)`。
3. 租约从旧 `resourceId` 升级到 `agentId + nodeId`。
4. 远程执行使用 `build_node_execution_adapter()`。
5. 健康检查、故障迁移和冻结绑定读取 Node/Agent 快照与健康投影。
6. `executionState["nodeAgentBindings"]` 保存新绑定；`resourceBindings` 仅由新绑定投影生成，服务旧 API 和旧测试。
7. API 与前端不再直接依赖旧资源表后，删除旧 Resource 真源和兼容门面。

Runtime 禁止在新调度失败时静默回退到旧 `SchedulerService` 或旧本地 Agent。任何缺少节点、凭据、健康、模型或容量的情况都应产生可读失败原因。

## Compatibility Surface

迁移期保留：

- 旧 `resourceId` 字段。
- 旧 `/resources` 查询响应。
- 旧执行状态里的 `resourceBindings` 投影。
- 旧测试需要的兼容解析。

迁移期不保留：

- 旧表作为写入真源。
- 旧健康状态作为调度依据。
- 旧 `resourceId` 作为新租约容量键。
- 新 Runtime 失败后回退旧调度。

## Testing Strategy

测试按风险分层：

- Store 合同测试：SQLite Node/Agent 重启后仍能读取画像、快照、凭据和 nonce。
- API 测试：`/nodes/register` 与 `/nodes/{id}/observation` 校验签名、时间窗、nonce、严格递增序号和状态持久化。
- Scheduler 测试：验证 Agent 白名单、模型、显存、隐私、owner scope 与 Step 约束共同作用于 Node。
- Lease 测试：验证 `agentId + nodeId` 容量键、幂等租约、释放校验、Redis/CAS 防并发超卖。
- Runtime 测试：验证 `wiring.py` 注入持久化新账本、Runtime 使用 Two-Layer Scheduler 和 Node Adapter、冻结绑定与故障迁移不再读取旧真源。
- Compatibility 测试：旧 `resourceId` 查询和 `resourceBindings` 投影仍能服务旧调用方，但不发生新旧双写。

## Acceptance Criteria

- Node/Agent SQLite Store 是默认运行时真源，重启后数据不丢。
- 调度结果一定是合法 `(agentId,nodeId)`，且失败原因可审计。
- 租约按 `(agentId,nodeId)` 锁容量，Redis 和内存实现语义一致。
- `/nodes/{id}/observation` 完成签名鉴权、重放保护、严格递增序号和持久化状态更新。
- Runtime 的远程执行、健康判断、冻结绑定和故障迁移全部走新账本。
- 旧 Resource 账本只剩兼容投影后，才能删除旧表和兼容门面。
