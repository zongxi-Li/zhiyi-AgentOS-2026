# PR-S02-01：Planning Commit Authority

状态：独立内存实现，未接入生产链，保持未提交。HEAD 为 S01-03 `ce1d67d117f678f211409fb4f47dee80fc24d37b`；入场已有未提交 S01-04，本轮未修改其8个代码/测试文件，SHA-256复核无漂移。未Commit、Push、部署、升级数据库或修改ADR。

## 范围与合同

新增 `src/contracts/planning_commit.py`、`src/components/planner/planning_commit.py`、`tests/components/planner/test_planning_commit.py` 及本记录。没有增加公开API、Feature Flag、Runtime挂接、数据库表或第二份TaskPlan/Graph/Run。

合同使用 `extra=forbid`、`frozen=True`，保留snake_case及既有camelCase别名约定：

- `FrozenPlanningSources`：Mission/Revision、Observation ID及指纹、PlanVersion、GraphVersion、Strategy指纹；正整数版本拒绝bool，指纹为64位小写SHA-256。仅支持已有正式规划上下文；首次规划无Observation/Graph时的来源合同留待S02-02明确，当前不伪造0版本或观察。
- `PlanningCommitRequest`：Proposal ID/type/指纹、Sources、RequestedScope、IdempotencyKey。Scope为1–256个唯一语义Key，排序规范化；执行身份、资源、调度状态和permission等额外字段均拒绝。它是可信应用侧请求，不注册为模型结构化输出。
- `PlanningCommitReceipt`：ACCEPTED / REJECTED / IDEMPOTENT_REPLAY。接受及重放必须携带Commit身份和Revision；拒绝不得伪造接受身份。
- `PlanningCommitRejection`：结构化code/reason，包括要求的8类以及STALE_OBSERVATION、STALE_STRATEGY。
- `PlanningCommitRecord`：要求字段之外保存完整Sources、Proposal ID/type、Scope及规范化Request指纹，以免回放丢失接受依据。sourceRevision明确为Mission源版本；status固定ACCEPTED；不保存第二套计划正文或执行对象。

## 调用及信任边界

`trusted application request → accept → revalidate contract → store lock → provider planning_guard → authorize → idempotency check → validate_sources → trusted proposal validation → recheck sources/authorization/idempotency → append immutable record → receipt`。

`CurrentPlanningStateProvider`提供`get_current_sources(mission_id)`的单一一致快照，替代独立采样三个版本的方法；还必须提供`planning_guard`、`authorize`和`validate_proposal`。Provider必须在guard内保护授权、Sources及候选注册表，依据真实候选证明ID/type/内容/来源绑定、Scope、已编译依赖闭合和控制/审核边界。权限来自注入的可信调用上下文，不来自request。无默认放行Provider，也未提供生产Runtime适配器。

服务只协调接受，不重新编译拓扑、不新增依赖算法、不凭合法JSON及相等版本认定Proposal可信。本轮单测Provider使用测试候选注册表；真实HTN/Horizon/初始计划及revise适配应在S02-02复用现有验证权威。

`validate_sources()`是只读预检；`accept()`在保护区内再次验证Mission、Plan、Graph、Observation和Strategy。可信Provider失败或guard退出失败不留下新成功记录，错误响应不暴露异常正文。锁顺序固定为Commit Store → Provider，生产适配器不得反向获取。

## 内存登记与幂等

InMemoryPlanningCommitStore支持按commitId、idempotencyKey及Mission最新记录查询；多Service共享同一Store时由RLock串行化接受、Revision分配和查询。commitmentRevision按Mission递增，与PlanVersion/GraphVersion/RuntimeRevision分开；parentCommitId指向该Mission前一接受记录。拒绝不消耗Key或Revision。

同Key、同规范化请求返回原Commit的IDEMPOTENT_REPLAY；不仅不同Proposal指纹冲突，同指纹但Scope/Sources/ID/type改变也返回DUPLICATE_CONFLICT。Scope顺序变化不算内容变化。历史接受之后Sources推进不改变历史事实，重放仅重新校验当前授权，并不声明旧Proposal仍可被执行；撤权则拒绝回执重放。历史记录不删除。

幂等Key在Store内为全局命名空间。不同Key即使引用同一Proposal也视为新接受请求，不做内容去重。单Store事务内的暂存记录在guard退出失败时回滚全部索引，其他线程不能观察半接受状态。RLock允许同线程Provider回调重入共享Store的服务，因此接受前再次检查幂等绑定；重入期间已接受的同内容请求返回原回执，不同内容返回冲突，不覆盖索引。

## 验证

在`apps/agentOS`、系统Python 3.14执行：

| 命令 | 结果 |
| --- | --- |
| `python -m pytest -q tests/components/planner/test_planning_commit.py --tb=short` | 45 passed，5.01s |
| `python -m pytest -q tests/components/planner tests/contracts tests/architecture tests/runtime --tb=short` | 711 passed，917.47s；补最后两项重入反例及幂等复核前的快照 |
| `python -m pytest -q tests/components/planner/test_planning_commit.py -k reentrant --tb=short` | 修复前2 failed，45 deselected，5.90s；同线程回调重入导致第二次ACCEPTED并覆盖Key绑定 |
| `python -m pytest -q tests/components/planner/test_planning_commit.py tests/contracts tests/architecture --tb=short` | 最终114 passed，12.30s；含完整47项Planning Commit测试及67项合同/架构测试 |

首轮44项通过、1项fixture setup error：真实Runtime fixture遗漏其runtime_boundary依赖导入。补齐测试导入后45项通过，没有跳过测试或改变断言目标。

覆盖请求/回执合同、记录不可变性、幂等内容冲突、所有来源Fence、伪造候选及扩大Scope、非闭合范围、控制阻塞、撤权、Provider失败、guard退出失败、验证中状态改变、Mission父承诺、并发重复与不同请求、同线程回调重入、共享Store和重启丢失内存语义。真实Runtime集成只使用临时SQLite，对比全部测试数据库（包括TaskPlan身份投影、Run、ACG、收据、Outbox等）及Agent调用，接受/重放均无变化。

最后修改仅涉及新接受服务的幂等复核及其两项反例，最终运行覆盖完整新增组件、合同门禁、架构门禁及真实Runtime零变更测试；未重复与该修改无调用关系的整个Runtime目录。没有运行AgentOS全量套件，不将扩大回归称为全量。既有测试、门禁和计时条件均未修改。`git diff --check`通过，暂存区为空。

## 限制与后续

本轮未挂接PlannerActionGateway、ReAct、RuntimePlanningApplication或SemanticRevisionService；未创建Run、绑定资源、调度节点或激活图。

记录仅存进程内；重启后ID及幂等索引丢失，新Store可重新从Revision 1接受相同请求。不同Store或不同进程不共享承诺版本，不具备durable authority或多实例CAS保证。接生产前需明确持久化、授权及安全边界的真实Provider、首次规划来源、候选内容可恢复引用和Outbox对账。当前记录只有候选引用及摘要，不能独立恢复Proposal正文，也不能作为执行令牌。

接受期间不执行LLM、拓扑求解或Runtime操作；Provider应只做有界可信校验。内存Store无容量/TTL策略；全Store锁优先保证最小实现的一致性，尚未优化跨Mission吞吐，也不提供硬截止期。S02-02接入时应保持Proposal ≠ Commit、Commit ≠ Execution、Commit ≠ Graph Activation。
