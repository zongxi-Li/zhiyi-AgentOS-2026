# Safe 持久防重放：阶段实施记录

日期：2026-11-15。承接认证HTTPS阶段的明确待办。本轮在独立功能分支实现，不合入正在修改的架构迁移分支；新增适配器仍位于既有 infrastructure/storage 层。

## 目标与实现选择

已有 `NonceStore` 端口和 `InMemoryNonceStore` 只在进程内保留记录。新适配器 `SqliteNonceStore` 使用Python标准库SQLite，供同一可信主机上的多个后段进程共享防重放状态。沿用现有HMAC协议与±60秒时窗，不改变wire字段、step、KV及回执语义。

内存方案继续作为显式短程实验默认；SQLite方案提供单机多进程和重启保留。Redis等跨主机存储暂不引入，以免扩大部署和依赖范围。

## 接口与事务

- 文件：`src/safe/infrastructure/storage/sqlite_nonces.py`，公开 `SqliteNonceStore`。
- `SqliteNonceStore.create(path, *, clock=time.time, max_entries=10000, max_per_credential=1000, timeout=0.25)` 显式初始化全新专用文件；路径已有任何文件即拒绝，不覆盖。
- `SqliteNonceStore(path, *, clock=time.time, max_entries=10000, max_per_credential=1000, timeout=0.25)` 只打开已有文件，SQLite URI `mode=rw`；重启、运行时丢文件均不得自动重建。
- 调用 `consume(credential_id, nonce, expires_at)` 返回原子首次消费结果；格式、期限、回拨、重复、容量、锁超时、数据库损坏/丢失均拒绝。数据库/文件错误不携带路径、SQL或原始异常上下文。
- 每次使用独立连接并显式关闭，无全局连接、跨线程复用或导入IO。`BEGIN IMMEDIATE` 串行化检查/清理/插入；`synchronous=FULL`。锁等待0–5秒范围，配置必须有限，不能无限阻塞认证。
- 使用独立application_id、schema version及精确表/索引检查。未知数据库、版本/结构不符和容量配置不一致不自动迁移、不删库修复。
- 专用meta单例保存全局/凭据容量和UTC高水位，nonce表以 `(credential_id,nonce)` 为主键、expiry建索引。有效条目不因容量压力驱逐；只删除 `expires_at < now`，保留验签时窗边界。
- UTC高水位和nonce消费在同一事务提交，并持久跨实例。有效重复/容量拒绝仍提交新高水位；非法时间不修改状态。回拨时拒绝到UTC追平，避免清理后的旧nonce再次可用。
- 时间以SQLite REAL保存现有浮点UTC值；超出 `abs(value) <= 2**53-1` 的时钟/期限拒绝，避免超大整数到REAL舍入改变边界。容量需在SQLite正int64范围内，不为极端数值引入文本时间或CAST查询。
- 事务提交后才返回True；提交结果不确定同样拒绝，由调用者使用新nonce发起新的业务查询，绝不重发可能推进KV的step。
- HTTP认证与模型同步工作统一在线程池完成，持久存储锁等待不阻塞ASGI事件循环；请求取消和停机排空继续等待认证线程结束后才释放在途计数。

## 分阶段提交与验收

1. 适配器及行为测试：重开/重启拒绝重放、时间边界、容量、不驱逐活跃记录、持久回拨保护、未知schema、故障、锁等待、有界文件增长观测，验证现有端口契约。
2. 认证/HTTP集成：同一数据库注入两个认证器/应用实例；实际多进程争用同nonce只有一个成功；服务重启后旧签名被拒绝，新nonce可用；存储故障固定拒绝、不分配KV。
3. 运行已有Safe回归及数据流测试，独立规格/质量审查，更新中文模块README和阶段结果，再提交功能分支并同步两远端。每次完整功能测试通过后提交。

## 能力边界

SQLite文件及其目录由部署者保护，数据库属于专用本机状态，不存密钥/激活/prompt。相同凭据的所有实例须使用同一文件和容量配置；不同主机、网络文件系统、复制副本和回滚备份不在本轮保证内。删除/替换/回滚数据库会破坏防重放，恢复时必须轮换凭据。文件大小受SQLite页和历史高水位影响，容量上限约束有效记录，不是文件硬字节配额。本轮不恢复会话/KV、不实现DP账本，也不宣称跨设备、公网、总deadline或取消协商已完成。

## 当前执行结果

- 适配器单元测试 84 项通过；独立进程/双实例 HTTP 集成测试 9 项通过；认证 IO、HTTP 和生命周期相关测试 59 项通过。
- `SqliteNonceStore` 不修改既有 HMAC wire 协议；它只替换 nonce 存储端口。认证和模型同步均在线程池运行，持久存储锁等待不会阻塞ASGI事件循环。
- 仍需质量审查、全 Safe 回归、文档和分支同步；本阶段不会勾选跨主机、公网、DP、会话持久化或模型性能完成。
