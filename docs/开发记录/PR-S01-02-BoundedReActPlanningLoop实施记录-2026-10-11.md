# PR-S01-02：Bounded ReAct Planning Loop 实施记录

**日期**：2026-10-11
**基准**：master `6bc5f8c9`（PR-S01-01 提交）之上的未提交工作区，等待独立架构验收
**状态**：代码与测试完成；新路径经环境开关 opt-in、默认关闭；未 commit、未 push、未部署

---

## 结论

S01-02 将单次 `decide_runtime` 演进为受预算约束的真实"模型—工具—模型"循环，并通过 Fake LLM + 真实 Runtime/SQLite 测试验证了完整受控路径（READ 多轮反馈、PROPOSE→revise→SemanticRevisionService 桥接、各类失败收敛）。AgentOS 全量 **1116 通过 / 0 失败**（既有 1079 + S01-01 22 + S01-02 15），其中 planner/contracts/architecture 子集 221、runtime 子集 280 定向回归全绿。

## 真实调用链

```
RuntimePlanningCoordinator.boundary()               （既有权威，未改动）
  └─ planner_for_run(run) → PlanningEngine          （facade；flag 开时挂循环）
       └─ engine.decide_runtime(observation, task_plan)
            └─ BoundedReActPlanningLoop.decide()     （components/planner/react_loop.py，新）
                 ├─ gateway.open_session(run_id)     （S01-01 网关，绑定持久 planningLoop 当前轮）
                 ├─ 循环 ≤ max_model_calls：
                 │    ├─ call_planning_model(llm, schema=PlannerLoopTurn)   （既有结构化输出适配）
                 │    ├─ use_tool → gateway.submit() → PlannerToolFeedback  （封闭投影回灌下一轮提示）
                 │    └─ decide → RuntimePlanningDecision
                 │         ├─ observationId 必须等于当前指纹
                 │         ├─ revise 必须与会话内登记的 plan_revision 指纹一致
                 │         └─ gateway.verify_binding() 交付前最后 CAS 复核
                 └─ 任何预算耗尽/故障/非法 → 显式 wait（可恢复 WAITING_REVIEW）
  └─ validate_decision / apply_decision              （既有审定与应用，未改动）
       └─ revise → SemanticRevisionService           （既有 S02 权威，未改动）
```

## 接口合同

- `PlannerLoopTurn`（contracts/planner_actions.py 新增）：`turnKind=use_tool|decide` 判别联合，use_tool 恰带一个 `actionRequest`（S01-01 `PlannerActionRequest`），decide 恰带一个 `finalDecision`（既有 `RuntimePlanningDecision`）。
- `PlannerToolFeedback`：工具结果的有界反馈投影（read 投影 / 登记回执（仅指纹与 Runtime 分配键）/ 拒绝码+理由），作为不可信数据进入下一轮提示。
- `ReActPlanningBudget`：统一预算——模型调用次数（默认 4）、工具动作次数（默认 6，透传网关）、上下文字符预算（默认 600k，按提示长度近似）、壁钟截止期（默认 240s，同时作为会话 TTL 与 `call_planning_model` 的共享 deadline）。
- `PlannerActionGateway.verify_binding(session)`（新增公共方法）：决策交付前对持久 Run/Observation/PlanVersion 的最后复核，失配返回拒绝并撤销会话。

## 修改文件（未提交）

| 文件 | 变更 |
|---|---|
| `contracts/planner_actions.py` | +`PlannerLoopTurn`、`PlannerToolFeedback`（41 行） |
| `components/planner/react_loop.py` | 新增 `BoundedReActPlanningLoop` + `ReActPlanningBudget` + `react_planning_enabled()` |
| `components/planner/unified_actions.py` | +`verify_binding`（6 行） |
| `components/planner/service.py` | +`react_loop` 构造参数与 `decide_runtime` 分派（默认 None，行为不变） |
| `runtime/workflow_runtime.py` | `_planning_engine_for_run` opt-in 装配：`AGENTOS_PLANNER_REACT_LOOP` 开 + 已注入意图 LLM 时逐 Run 构造引擎并挂循环，审计走 `trace_store` Runtime Event（与 planning_loop 同款）；关闭时路径与原先完全一致 |
| `tests/.../test_react_loop.py` | 新增 15 个测试 |
| `tests/.../test_unified_actions.py` | 源码扫描不变量演进：协议只允许经 opt-in 缝隙引用（react_loop/service/flag 门控 facade） |

## 关键设计决策

1. **结构化输出适配而非原生 Tool Calling**：审计确认 `IntentLLM` 协议只有 `generate_json(prompt, schema)`，网关无工具调用接口；判别 Schema 完全复用既有 `call_planning_model` 的超时/重试/提示词元数据边界，零网关重构。
2. **revise 桥接以登记指纹为凭**：`decide revise` 携带的 `TaskPlanPatch` 必须与本会话内已 PROPOSE 并通过网关校验的 `plan_revision` 候选指纹一致，否则收敛 wait——PROPOSE 因此成为 revise 的必经前置，模型无法凭空直提修订。candidate_tasks/method 永远只是候选，无任何进入执行图的通道。
3. **迟到结果丢弃**：每次模型调用返回后先查截止期，超时则丢弃内容直接收敛——`test_deadline_discards_late_model_result` 用"模型在截止期后返回 complete"验证了决策未被采用。
4. **重启/重入安全**：会话是边界内临时对象，重启后旧 sessionId 确定性 `UNKNOWN_SESSION`；轮次权威仍是持久 RuntimePlanningState（"observed→requested→decided→applied"标记逻辑未动），重复观察不重复调用模型、重复应用被 applied 标记拦截（既有测试覆盖，本轮未改）。
5. **测试时钟与模型时钟解耦**：注入测试单调钟时不向 `call_planning_model` 传递本循环 deadline（其内部用真实 monotonic，混用会造成假超时），循环自身的截止检查仍然生效。

## 实际测试结果

| 套件 | 结果 |
|---|---|
| `tests/components/planner/test_react_loop.py`（新） | 15 passed |
| `tests/components/planner` + `tests/contracts` + `tests/architecture` | 221 passed |
| `tests/runtime` | 280 passed |
| 全量 `python -m pytest -q` | **1116 passed / 0 failed**（3:49） |

Fake LLM 每一轮都从真实提示读取 `toolFeedback` 并断言其内容后才出牌（读取不到期望反馈即抛错）——证明反馈回路真实存在，不是脚本模拟。覆盖矩阵：真实多轮 READ→反馈→决策、重复工具请求幂等重放、PROPOSE→revise→SemanticRevisionService 全链（源 Run SUPERSEDED、替换 Run plan v2 完成执行）、未登记修订收敛 wait、边界中途 Observation 变化/会话撤销收敛、模型预算/动作预算耗尽、截止期迟到结果丢弃、模型故障、非法轮输出、伪造 observationId、工具故障反馈后继续、模型故障经审核批准恢复（等价重启恢复）、flag 默认关单次路径逐字节不变（提示词无 toolFeedback、单次调用）、facade opt-in 行为。

测试中发现并修正的三处问题（均为本轮引入，未触及生产既有路径）：测试注入时钟与 `call_planning_model` 真实单调钟混用造成假超时（修复=仅共享真实时钟时传递统一 deadline）；测试桩 Agent 不满足 task_understanding 输出合同（缺 `task_summary`，对齐既有桩）；子类覆写网关方法名写错（`_read_evidence`）。

## 失败恢复语义

所有非正常终止统一收敛为显式 `wait` 决策（reason 前缀 `Bounded ReAct Planner:`），由既有协调器审定并落到 WAITING_REVIEW 屏障——外部审核批准即可恢复，无伪造 complete/success；模型抛出的意外异常同样被收敛（单次路径的既有语义是协调器兜底 safe wait，两条路径一致）。

## 剩余风险与停留在此 Proposal 阶段的能力

- **candidate_tasks 与 method**：仅会话内登记，无消费方；进入执行图的唯一通道仍是 plan_revision→revise→S02。HTN 方法选择、Adaptive Rolling Horizon（按远期意图动态决定提交视界）、S02 Planning Commit、S03 Progressive ACG 均未实施（范围边界）。
- **revise 语义仍是"版本化替换整个 Run"**（替换 Run 重执行全部步骤，测试如实断言）；已执行前缀不可变是后续 PR 的目标。
- **上下文预算按提示字符数近似**，非精确 token 计量；预算默认值（4 次模型调用/6 次动作/240s）未经真实模型调参，接入真实 LLM 前需实测校准。
- **会话内存态**：跨重启不恢复（设计取舍，重启后确定性 UNKNOWN_SESSION）；网关会话字典在长寿命进程内按 Run 积累（每会话 ≤ max_actions 条记录，量级可控，未来可加淘汰）。
- **真实 LLM 端到端未验证**：本轮全部为确定性 Fake LLM；真实模型在该判别 Schema 下的服从率、多轮行为质量需在验收环境用真实供应商实测。

## 2026-10-12 提交前复核

- 当前 HEAD 为 `6bc5f8c9`，S01-02 的 8 个变更路径均未暂存；没有其他工作树。
- 用户在本轮提供了独立架构验收全文，结论 **ACCEPT（无 P0）**：planner/contracts/architecture 221、runtime 280、全量 1116 通过。已对照实际变更核实四项权威边界：替换 Run 的既有重执行语义、共享绝对截止期、最终应用 CAS、持久轮次与幂等恢复。该报告针对补充修复前的 5 修改 + 2 新增 + 1 文档；不把其结论冒称为修复后的独立验收。
- 代码复核发现最终决策交付前 `verify_binding()` 未检查会话撤销状态，撤销后直接返回 `decide` 可绕过工具提交侧的撤销门禁。补充签发实例归属、撤销状态与截止期检查，保留动作预算耗尽后模型仍可安全作出最终决策的原有行为。
- 新增 2 项回归：撤销后直接返回 `complete` 收敛为 `wait`；外部网关的会话及过期会话均不能交付决策。
- 修复后定向运行 `test_react_loop.py` + `test_unified_actions.py`：**39 passed**；重新启动全量 `python -m pytest -q`：**1118 passed / 0 failed**（224.14s，既有 PyPDF2 弃用警告 1 项）。`git diff --check` 通过。
- 按用户授权将 S01-02 的 8 个明确路径整理为本地 Commit，标题 `feat(agentos-planner): 实现受控 ReAct 规划循环与工具反馈闭环`；未 Push、未部署、未操作生产数据库。提交 hash 由 Git 查询，不写入自身提交树。
