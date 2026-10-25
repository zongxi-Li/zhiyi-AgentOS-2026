# INT-2C 执行准入独立审查收束

日期：2026-10-25。入场本地与 GitHub master 均为 `250a04c93c8734f355f252938a7fecd2812752a7`，工作区、暂存区及未跟踪文件为空。保留用户文档删除，不恢复。阶段结果：**SELF-TESTED（受限固化，等待独立复验）**。

## 已证实的 P1 红态

真实 FastAPI + 生产装配 Runtime + 临时 SQLite，开启 `AGENTOS_C2_EXECUTION_DISPATCH`，完成正式 Initial 链直至 Permit ISSUED，未发送 Dispatch，准备合法资源和可信主体后直接执行 `runtime.execute_prepared_run`。

初始拒绝断言失败：`DID NOT RAISE ValueError`（24.39s，退出码 1）。增强证据断言后的同一反例再次失败（22.79s，退出码 1），实际输出：

```text
Permit-only bypass: calls=['A', 'B', 'C'], NodeExecution commits=3
```

这证实 INT-2C 的 Coordinator 准入检查未覆盖 Runtime 直接入口。历史 SELF-TESTED 不等于最终执行边界的生产验收；此前“未发现新增 P0/P1”的自审结论在此反例下被推翻。

## 单一边界修复

- Runtime 默认 `execution_dispatch_enabled=False`，装配从现有配置显式设置该模式，不能把 Store 缺失误认为模式关闭。
- 只在 `_claim_acg_execution` 的正式 Activation Head 分支增加必要条件：原 Run lock + OS fence + 同一 Workflow SQLite 读取事务中，用原 `SQLiteExecutionDispatchStore` 校验 schema、行完整性及 Dispatch。
- Command 必须匹配当前 Mission、Run、已验证的正式 Permit、Graph ID/version、当前可信主体；接受时 Runtime revision 不得晚于当前 Run。Store 路径必须为同一 Workflow ledger，缺失/解绑、损坏或错误关联均拒绝。
- 原 Permit `assert_dispatchable`、未结清操作检查、执行 slot claim 和调用前 guard 全部保留。不由 HTTP/前端生成 Command Record，不逐个路由打补丁。
- 模式关闭保持已验收兼容行为。没有新的 Authority、Schema、状态机或执行器。

`execute_prepared_run`、`resume_from_checkpoint` 和 `apply_review` 的 ACG 续跑均进入 `_execute_acg` → `_claim_acg_execution`。Retry 的恢复输入与 successor Run 仍由原 Recovery Coordinator 决定，实际执行也必须经过该共享边界。审核决定可能合法持久化，但缺少 Command 时不能因此取得后续节点执行资格。

## 永久回归和门禁合同

`apps/agent/tests/test_agentos_c2_dispatch_admission.py` 包含：无 Command + 已有 Permit 的直接执行拒绝、Checkpoint 恢复拒绝、损坏 checksum、错误 Permit/GraphVersion/Mission/actor、Store 解绑、Dispatch disabled 兼容，以及 Review 续跑不能替代丢失 Command。断言零新增节点调用/NodeExecution，且认领失败不残留 slot。

原 Dispatch 21 项继续覆盖有效 Coordinator 执行、取消、并发、真实进程退出、已完成节点不重复、未知副作用阻断、审核及资源清理。新增 `apps/agentOS/tests/runtime/test_dispatch_admission.py` 将真实 Permit-only 反例纳入 Native 冻结门禁。

固定摘要更新遵循原合同：保留 INT-1 基线 JSON、摘要及全部既有测试映射；只更新已修改 wiring 的外部固定摘要，并增加 WorkflowRuntime/Dispatch Store 到真实反例的映射。装配、失败清理、Schema 与漂移强制选测断言不减少。不是删除历史覆盖或拿当前 HEAD 代替固定基线。

## 实测结果

- 单个红转绿关键反例：1 passed in 13.86s，退出码 0。
- 准入/Dispatch 组合：30 passed in 320.59s，退出码 0（收集时尚未包含随后新增的 Review 缺失命令测试）。
- Review 缺失命令永久反例：1 passed in 22.27s，退出码 0。
- `test_freeze_gate_integrity.py`、`test_runtime_assembly_failure_cleanup.py`、`test_c2_schema_upgrade.py`：109 passed, 1 warning in 174.96s，退出码 0。

最终 API 定向子命令（仓库根目录，Python subprocess 同时记录源码摘要）：

```powershell
python -m pytest apps/agent/tests/test_agentos_c2_dispatch_admission.py apps/agent/tests/test_agentos_c2_dispatch_http.py apps/agent/tests/test_agentos_c2_http.py apps/agent/tests/test_agentos_c2_permit_http.py apps/agent/tests/test_internal_service_auth.py apps/agent/tests/test_agentos_control_contracts.py apps/agent/tests/test_agentos_v2_api.py apps/agent/tests/test_execution_runtime_application_wiring.py apps/agent/tests/test_execution_coordinator.py -q --disable-warnings --maxfail=1
```

最终核心/生命周期子命令（cwd=`apps/agentOS`，默认 DB/Chroma 环境路径隔离到临时目录）：

```powershell
python -m pytest tests/components/planner/test_graph_handoff.py tests/components/planner/test_graph_handoff_recovery.py tests/components/planner/test_execution_permit.py tests/components/planner/test_execution_permit_audit.py tests/components/planner/test_initial_execution_permit.py tests/components/planner/test_permit_recovery.py tests/components/planner/test_permit_recovery_final_audit.py tests/components/planner/test_production_authority_assembly.py tests/runtime/test_fault_recovery.py tests/runtime/test_review_recovery_extraction.py tests/runtime/test_dispatch_admission.py -q --disable-warnings --maxfail=1
```

核心/生命周期：165 passed, 2 warnings in 700.96s，`CLOSEOUT_CORE_EXIT_CODE=0`。API 最终集合重新执行并落盘：133 passed, 4 warnings in 482.14s，`API_EXIT_CODE=0`。六个源码/测试/门禁摘要运行前后逐项一致。`git diff --check` 退出码 0。没有运行无关全量 pytest，也没有运行/宣称通过整个五分钟 freeze_gate.py，没有清空门禁历史耗时缓存。

入场 Git blob SHA256（`git show 250a04c:<path>` 原始字节；工作区摘要含 Windows 换行，两者用途分别为可复现历史与测试时完整性）：

| 文件 | 入场 SHA256 |
| --- | --- |
| `workflow_runtime.py` | `a04bb0f7fda0b7e9a494161c515e8942ae94782cef11679cd343afd6a36170e1` |
| `execution_dispatch_store.py` | `6c7dbeb3ad6de787ab53439ba4175825740f6b7502706e58d8ec953cca758a09` |
| `wiring.py` | `b9e4b1f58910a46194b8f306cf829f68127e7e80931e40b76cdb3b5063e83931` |
| `freeze_gate.py` | `af9ff6d92d4e85f723e749db091a71d01565baaea06ad569ef416c09b8657f69` |

最终 API 门禁前源码 SHA256（运行后比较）：

| 文件 | SHA256 |
| --- | --- |
| `apps/agentOS/src/runtime/workflow_runtime.py` | `0e7bdd692effcb2e3c6842dc870c8e349e16d0192b42b0dae41a3a0b2c4e1c51` |
| `apps/agentOS/src/support/stores/execution_dispatch_store.py` | `18a87171763682c131e0ac2767f56c204c98b933f46b453d447d2571d0041e4c` |
| `apps/agent/app/execution/wiring.py` | `29f9dd70a4803fb8d0329ef230eb854fdd4e190fda013473c270b7070375ecbf` |
| `apps/agent/tests/test_agentos_c2_dispatch_admission.py` | `d99cb1a8aeef7409eb097f5ba1c6948eddd3dc50ce22300bd442483444af5899` |
| `apps/agentOS/tests/runtime/test_dispatch_admission.py` | `edacabf75ad5bf4fbc2fbe299ef25a20aa0fe5a7284c2b74e708e04c5320b831` |
| `scripts/freeze_gate.py` | `d4db98383cdbe4f8e19764f0777253e7f37d2d9a14e8e47b89bd873a6f4843f6` |

## 收束边界

通过后仅按受限合同固化 INT-2C，等待独立复验。P2/P3 仍包括单 Runtime 部署、显式 Schema 升级及生产开关关闭、未知外部副作用的人工处置、同步 SQLite/权威验证的性能边界。不宣称跨库原子性或远端 exactly-once。

关键红态已转绿，定向门禁通过，自审未发现遗留或新增 P0/P1，允许进入 INT-2D。后续前端、网关转发及最小只读 Dispatch 发现能力单独记录于 `PR-C2B-INT-2D.md`。本阶段提交由 `git log -- docs/audits/PR-C2B-INT-2C-CLOSEOUT.md` 唯一定位，完整 SHA 与最终远程状态在 INT-2D 报告归档，避免提交内自引用。
