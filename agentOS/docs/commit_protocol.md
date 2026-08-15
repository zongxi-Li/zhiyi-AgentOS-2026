# 节点提交恢复协议

## 目标

一个 ACG 步骤会依次涉及 Agent 或工具调用、输出引用、记忆、通信血缘、Trace 和 checkpoint。它们位于不同服务甚至不同 SQLite 文件中，不能把这件事误称为单一数据库事务。

本协议使用稳定 `commitId` 和可恢复提交记录，保证同一步骤尝试在中断后不会被误当成新的业务操作。

## 提交标识

格式为：

```text
commit:{runId}:{stepId}:{attempt}
```

同一运行、步骤和尝试次数始终使用同一个标识；只有真正进入新的重试次数时才会生成新的提交边界。`commitId` 仅包含标识，不包含输入、输出、记忆正文或工具参数。

## 两个阶段

```text
prepared
  → Agent / Tool 调用（携带同一 commitId）
  → 输出、记忆、血缘等本地副作用
  → committed（只保存引用与安全审计元数据）
  → Runtime 投影 Trace 和 checkpoint
```

- `prepared`：调用可能尚未完成。恢复时仍可调用，但必须传递原 `commitId`，让 Agent、模型或外部工具实现自身的幂等去重。
- `committed`：输出、上下文、记忆、审计和血缘的安全引用已确定。恢复时不再调用 Agent，而是复用引用；条件路由所需值仅按 `outputRef` 临时读取，不能写进提交记录或 checkpoint。

## Trace 重放

`node_completed` 事件携带 `commitId`。Runtime 若已看到同一提交对应的 `step_succeeded` Trace，就不会再次追加步骤成功、记忆访问或通信血缘事件，只持久化当前引用型状态。

## 外部副作用边界

原生知识检索工具已收到 `commitId`。新增 Agent、模型或工具适配器时，应将该值转为供应商支持的 idempotency key；不支持幂等键的外部服务必须在适配器中明确标注为“至多一次无法保证”，不能被当作完全可恢复操作。

## 当前保证与限制

- 进程重启后，SQLite 提交记录和输出引用可恢复。
- 完成态重放不会重复 Agent 调用、记忆写入或 Trace 投影。
- 准备态恢复会使用相同 `commitId` 重试，避免扩散新的外部操作标识。
- 当前独立的值仓库、记忆仓库与 checkpoint 文件不是分布式事务；后续若需跨库原子提交，应迁移到同一事务型存储或引入明确的补偿任务表。
