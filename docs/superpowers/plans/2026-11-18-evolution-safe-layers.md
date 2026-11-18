# Evolution SAFE Layers Implementation Plan

> **For agentic workers:** Use executing-plans inline; this session is already authorized for analysis and implementation.

**Goal:** 分层现有演化闭环，保证审核原子性和可重放回执，接通注入式离线图演化流程。

**Architecture:** contracts 保持唯一；application 只编排纯合同和 ports，Run 投影移到 integration，内存/SQLite 移到 infrastructure。旧模块保留兼容门面。

**Tech Stack:** Python3.13、Pydantic2、SQLite、pytest。

## Task 1：发布一致性与证据门槛

- [x] 在 `TEST/tests/components/evolution/test_publication.py` 写失败测试：SQLite 触发器使提案更新失败时版本/活动指针必须回滚；同请求重试、重启查询、双连接竞争；重复轨迹不跨越门槛。
- [x] 运行 `python -m pytest -c apps/agentOS/pytest.ini TEST/tests/components/evolution -q`，确认新增断言暴露缺失能力。
- [x] `contracts/evolution.py` 增加 `EvolutionPublicationReceipt`；port 增加 `commit_approval(value, proposal, expected_active)` 和 `get_receipt(proposal_id)`。
- [x] 在单次 `BEGIN IMMEDIATE`/内存锁内校验并保存版本、已审核提案、活动指针及回执。重复请求校验回执的提案指纹与审核人，返回旧结果。

```python
first = service.approve(proposal, approved_by="reviewer")
assert service.approve(proposal, approved_by="reviewer") == first
assert service.store.get_receipt(proposal.proposal_id).policy_version == first.version
```

## Task 2：职责拆分

- [x] 迁移 `service.py` 的用例到 `application/policy.py`，评分/验证到 `domain/policy.py`，Run 投影到 `integration/trajectory.py`。
- [x] 迁移 `store.py` 到 `ports/store.py`、`infrastructure/memory.py` 和 `infrastructure/sqlite.py`；`bootstrap/policy.py` 显式装配。
- [x] 保留 `service.py`、`store.py` 历史导入；`policy.py` 只导出用例与 DTO。应用装配显式注入存储，runtime 显式调用轨迹适配。
- [x] 增加 AST 架构测试，禁止 application 导入基础设施/运行时，禁止 domain 和 ports 导入实现层。

## Task 3：离线图用例

- [x] 在 `test_graph_evolution.py` 写未配置、证据错绑、评测错绑、退化/成本越界和注入端口的发布测试并观察失败。
- [x] 在共享合同增加 `GraphEvolutionEvaluation`，在 `ports/graph.py` 定义 generator/validator/evaluator/publisher；application 编排，`graph_service.py` 重导出。
- [x] 发布时重新校验提案并计算完整指纹，比较评测的提案绑定与配对样本；要求非空审核人，调用注入发布器。无发布器拒绝而不是假成功。

```python
evaluation = service.evaluate_proposal(proposal)
service.apply_approved_proposal(proposal, evaluation=evaluation, approved_by="reviewer")
```

## Task 4：验证与交付

- [x] 运行演化测试、`apps/agent/tests/test_general_golden_evolution.py`、`apps/agent/tests/test_execution_runtime_application_wiring.py`；检查旧 Run 快照不变、新 Run 使用预算。
- [x] 更新进化器 README，保留已有分析内容并附实际目录/能力边界；记录命令与通过数量到 `docs/superpowers/reports/2026-11-18-evolution-safe-layers.md`。
- [x] `git diff --check` 并核对本轮文件，不覆盖原有 `apps/agentOS/README.md` 改动。

执行结果：156 项联合回归通过，3 项现有依赖警告。独立审查发现的等价 JSON 重放和来源 Run 留出检查均已补失败测试并修复。生产图校验/真实回放/发布适配器按设计保持未接通，未将端口测试替身当作生产能力；额外旧 API 夹具失败单列于报告。
