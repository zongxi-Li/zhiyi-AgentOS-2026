# 工作区投影更新协议

工作区采用两条用途不同的 SSE：

- `GET /api/agentos/v2/runs/:runId/events`：模型输出、节点执行等临时事件，随 Run 结束关闭。
- `GET /api/agentos/v2/missions/:missionId/workspace/events`：工作区投影失效通知，独立于所选 Run 的终态。

工作区读取接口增加 `projectionSchemaVersion: 1` 和非负整数 `projectionRevision`。
通知事件为 `workspace.projection.updated`，JSON 字段为 `schemaVersion: 1`、
`missionId`、`projectionRevision`、`eventType`，SSE `id` 是版本号。
通知不包含正文，也不授予任何操作权限，现有 Mission 访问检查保持生效。

Identity 与 Runtime SQLite 库分别维护 Mission 的持久化版本计数，相关表的 INSERT、
实际 UPDATE、DELETE 通过触发器在源事务内递增版本。失败事务回滚版本。
读接口返回两源计数之和；这与执行授权的 `runtimeRevision` 无关。
新库初始化时安装附加版本表和触发器；已有持久化卷先通过管理工具显式升级，
再由启动检查验证。升级不重写历史 Run，也不重置已有版本。

版本是保守的失效水位，不是跨库一致性快照，也不作为内容 ETag。
HTTP 在拼装前读取水位，因此并发发生的新写入会要求后续补拉，不会被标成已读取。
本进程提交后唤醒订阅者；其他进程的提交由 SSE 服务端每 15 秒核对一次轻量版本查询补齐，
此检查不重建工作区。没有更新时只发送心跳，前端不发起工作区 HTTP 轮询。

订阅先登记队列，再读取当前版本；首帧与每次重连都发送当前水位。
前端只在目标版本高于已加载版本时合并刷新。在途请求不被通知打断，
读取完成后仍落后于目标版本则继续补拉；失败时延迟 5 秒重试。
切换 Run 保留 Mission 订阅，隐藏或卸载工作区时断开，重新激活时重新握手。
Run 完成后仍可收到迟到的任务图、产物与来源关联更新。

Workspace、Run、Copilot 共用 `utils/sse.ts` 中的帧读取与解析，统一处理分块、
UTF-8、取消及 reader 释放；各入口分别负责业务校验、完成条件与重连策略。
工作区请求只在结束时统一调度下一次版本补拉，通知到达时只合并目标版本。
Identity 与 Runtime 共用 `WorkspaceConnection` 的提交后唤醒机制；事务失败不通知，
嵌套事务只由最外层提交，数据库触发器继续负责版本的原子递增。
