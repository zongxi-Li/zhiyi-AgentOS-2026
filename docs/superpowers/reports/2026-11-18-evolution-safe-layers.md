# 进化器 SAFE 分层与原子发布实施记录

日期：2026-11-18（Asia/Shanghai）。本地分支：`feat/evolution-safe-layers-20261118`，基线 `2c6d8547`。
工作区原有 `apps/agentOS/README.md` 改动保留；进化器原有未跟踪 README 的分析全文保留，并补充最新实现。

## 分析结论与实施内容

当前 General 的有效演化能力是记忆预算策略的受控发布。768 token 提案仍为兼容示例，新颖度仍为 0；本轮没有将其描述为自动学习或拓扑优化。
SAFE 和核心测试已经分别迁移到 `apps/agentOS/src/components/safe`、根目录 `TEST/tests`，按最新结构实施。

- 共享 DTO 仍唯一存在于 `contracts/evolution.py`，新增策略发布回执、图离线评估及图发布回执。
- 进化器内部拆为 application/domain/ports/infrastructure/integration/bootstrap；旧 `service.py`、`store.py` 保留兼容。
- 新轻量公开入口 `policy.py` 只依赖合同、领域和端口；应用显式注入 SQLite，Run 适配移出策略用例。
- 审核在同一事务/锁内重验提案与评分、创建版本、切换活动指针、标记批准、保存回执；失败全部回滚。
- 同提案/内容/审核人的重试返回原版本，异内容或审核人冲突；回执跨重启与回滚不变。
- 新增 `GET /agentos/v2/evolution/proposals/{proposal_id}/receipt`，未发布返回 404。
- 重复轨迹不增加门槛，内容冲突拒绝；空审核人、布尔值及非有限预算拒绝。
- 图用例具有注入式生成、专业校验、配对离线评测、正式发布四个边界。
- 实现确定性验证器插入候选算法：同图同版本的不同来源证据，至少两次相同步骤失败，显式 capability→validator 映射，按失败数及标识排序。
- 图门槛默认三条证据；评分绑定完整提案指纹及评测版本，留出样本与来源轨迹/Run 互斥，质量不下降，默认成本不增加。
- 发布阶段重新调用可信评测器，交给正式发布 port；使用输入快照，检查返回回执身份。

## 验证环境与命令

Python：`C:/Users/22935/AppData/Local/Programs/Python/Python313/python.exe`。
复用现有隔离依赖目录，不修改依赖清单，不在全局安装包：

```powershell
$env:PYTHONPATH = 'E:/Project/Kinlin_AI/tmp/agentos-http313;E:/Project/Kinlin_AI/tmp/agentos-sdk313'
& C:/Users/22935/AppData/Local/Programs/Python/Python313/python.exe -B -m pytest -c apps/agentOS/pytest.ini `
  TEST/tests/components/evolution `
  apps/agent/tests/test_general_golden_evolution.py `
  apps/agent/tests/test_execution_runtime_application_wiring.py `
  apps/agent/tests/test_agentos_v2_api.py::test_v2_evolution_receipt_survives_replay_and_rollback `
  TEST/tests/test_runtime_import_boundary.py `
  TEST/tests/runtime/test_architecture_naming.py `
  TEST/tests/components/planner/test_graph_revision_commit.py `
  TEST/tests/components/planner/test_graph_revision_audit.py `
  -q -p no:cacheprovider --tb=short
```

最终联合命令：**156 passed，3 warnings，430.97 秒**，覆盖演化、回执 API、General 黄金链路、应用装配、运行时导入/命名边界和现有图修订提交/审计。
此前专项验证：演化+回执 API+运行时导入/命名边界 66 passed；General 黄金链路+应用装配+当时演化测试 51 passed。
演化最初基线为 7 passed；新增失败测试先复现问题，再修改实现。

专项覆盖实际 SQLite 触发器中止（提案状态写入、回执写入）、双连接不同提案 CAS 竞争、相同提案并发重试、关闭重开后恢复回执、回滚不改历史回执。
General 黄金链路验证新 Run 采用 768 token，旧 Run 策略版本与步骤快照保持不变。
架构测试通过 AST 和子进程导入确认用例层不引用基础设施、Runtime 或 Run 合同；轻量门面导入不加载 SQLite/Runtime。

## 独立审查与修复

按 requesting-code-review 技能安排只读审查，确认并修复：

1. SQLite 曾按 JSON 字节判断同一证据，等价对象字段顺序不同会误报冲突；现在反序列化比较合同内容，与内存实现一致。
2. 留出检查曾仅排除 trajectoryId，漏掉真实投影的 task.runId；现在两种来源标识均排除。

同时固定适配器调用间的输入快照，防止浅冻结 DTO 中的 list/dict 在验证到发布之间改变。
三项均新增失败复现后修复。

## 已知边界

图生产快照校验器、真实任务回放评测器和正式版本发布适配器尚未接入，产品 API 没有开放图发布；测试中的图评测/发布替身只证明门槛与委派。
缺依赖显式拒绝，未直接写 RuntimeGraph，未建立第二套 TaskPlan/图版本权威。Skills 抽象和生命周期算法仍未实现。
评测器应产生可复现报告；传入先前报告发布时，需与再次计算的报告相同。正式发布器需实现主体鉴权、CAS、幂等回执和原子发布。
旧策略记录完整保留，新表不为历史批准提案补造回执；历史无回执的批准提案不允许自动重新批准。

额外执行旧 `test_v2_projects_scheduling_and_versioned_evolution_without_bodies` 时，在进入演化断言前失败：其 `_runtime()` 无身份实例依赖已移除的隐式 workflow-step 建图，抛出 `workflow step promotion was removed`。
本轮没有修改该旧测试或恢复旧建图路径；新增回执 API 测试直接准备策略证据，覆盖 404、审核重放、审核人冲突及回滚后的回执一致性。
该额外失败与联合命令的验证范围分别记录，不表示整个仓库测试均已通过。

最终 `git diff --check` 通过；26 个进化相关源码文件完成语法解析，新增文档相对链接已核验。

出现现有依赖警告：Starlette/AnyIO 弃用、Pydantic Settings 类配置弃用，以及 rollback 字段 schema alias 警告。

## 交付位置

- [模块说明](../../../apps/agentOS/src/components/evolution/README.md)
- [设计](../specs/2026-11-18-evolution-safe-layers-design.md)
- [实施计划](../plans/2026-11-18-evolution-safe-layers.md)
- [故障与并发验证](../../../TEST/tests/components/evolution/test_publication.py)
- [图演化门槛验证](../../../TEST/tests/components/evolution/test_graph_evolution.py)
