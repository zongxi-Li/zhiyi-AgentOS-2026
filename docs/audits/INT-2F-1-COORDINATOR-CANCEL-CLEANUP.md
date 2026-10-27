# INT-2F-1：Coordinator 首次调度前取消清理

日期：2026-10-27。研发任务结论：**SELF-TESTED**，等待独立验收。V1 尚未正式冻结；本次没有运行正式冻结门禁，也不以其为研发完成前置条件。

## 入场及任务选择

HEAD 为 `53eb030023dd2f2c631a222df3786dfd18fc1fa5`，暂存区为空。实时读取 GitHub 与 Gitee 的 master 均为该 SHA；仅查询，没有 fetch、提交、推送或部署。`mirror` 配置了两个 push URL，本次没有使用其推送能力。

入场已有两份门禁源码修改及六份未跟踪审查文档，均予保留。审阅 Coordinator、Dispatch HTTP、Dispatch Store、共享 Native 认领边界及 INT-2C/2D/2E 阶段记录，区分如下：

| 事项 | 当前判断 | 本轮依据 |
| --- | --- | --- |
| 正式执行必须有持久 Dispatch | 已实现，不能重新认定缺失 | `submit_permitted`、Store、`_claim_acg_execution` 的 `assert_admitted`；本轮 Native 拒绝与 HTTP 回归 |
| 正式主体、写权限、幂等及竞争请求 | 已有控制与回归 | HTTP 可信身份、Authority 校验、持久单 Run 命令及最终 Native 校验；本轮拒绝/并发测试 |
| Dispatch ACK 丢失、Checkpoint、未知副作用恢复 | 已实现受控恢复 | 原 Recovery Coordinator 和现有真实进程故障测试，本轮回归 |
| human_in_loop 和 final 公开边界 | 已有修复，非本轮重新实现 | INT-2E CLOSEOUT 记录、`human_review_policy.py` 与本轮人工审核 HTTP 测试 |
| Workbench 正式控制链、真实 IAM/Provider/SSE | 有历史验收证据；本轮未重做浏览器跨栈验收 | INT-2D、INT-2E 与 RC 清单，不把历史记录当作本轮实测 |
| 多租户、会话撤销、Provider 故障、灾备和原生宿主 | 尚待相应生产环境复验，不能仅凭文档判定代码缺失 | 现有生产就绪性限制 |
| 首次执行前取消的 Task 清理 | **本轮确认并修复的 P2** | 旧 shutdown 只清理其自身取消的 Task；显式 `cancel()` 的同一边界存在真实反例 |

选定问题：Task 在其协程首次运行前被取消，不会进入 `_run_managed` 的 `try/finally`。原 `cancel()` 只发出取消请求，结束的 Task 因此会一直留在 `_tasks`，直到 shutdown 或同 Run 再次覆盖。这是长时间运行服务的任务所有权与资源引用收束缺口；没有将其夸大为已证明的执行越权。

## 范围与合同

仅修改三份源码/测试文件：

1. `apps/agent/app/execution/coordinator.py`：两条任务创建路径统一 `_track_task`；通过 Task 完成回调 `_forget_finished_task` 清理句柄。
2. `apps/agent/tests/test_execution_coordinator.py`：Legacy/正式路径、首次运行前后取消、旧 Task 回调不误删新 Task 的永久回归。
3. `apps/agent/tests/test_agentos_c2_dispatch_http.py`：真实 Runtime/临时 SQLite 下的首次调度前取消、重放和重建集成回归。

公开接口、返回值、持久 Dispatch、Permit、生命周期及恢复状态机均不改变。`cancel()` 仍是取消请求；清理在 Task 实际结束、完成回调运行后收敛，不承诺调用返回瞬间任务已全部结束。

回调只处理 `task.done()` 且字典中仍是同一 Task 的条目。同步回调在同一事件循环内完成比较和移除，中间没有 await，避免旧任务结束时删掉新任务。原 `_run_managed.finally` 和 shutdown 清理保留，重复清理安全。没有增加跨线程调度支持。

关键链路仍为：HTTP 读/写权限检查 → Runtime 持久取消 → Coordinator.cancel → Task.cancel → 完成回调。正式执行仍为持久命令接受 → Coordinator 管理 Task → 原 Runtime/Permit/Native Scheduler；没有新增 Authority、Store、Schema 或执行器。

## 红绿证据

证据目录：`.tmp-tests/int2f-1-fbdb81ef2efa467c81582d8d544e57db/`。每轮 `.json` 保存实际命令、cwd、真实退出码、墙钟及五份源码的前后 SHA-256；同名 `.log` 保存完整 stdout/stderr。各轮均未在执行中修改受测源码。

| 记录 | 结果 | 真实退出码 | 完整墙钟 |
| --- | --- | --- | --- |
| `coordinator-red-confirmed`，Coordinator 模块 | 2 failed / 8 passed；两条首次执行前取消路径均残留句柄 | 1 | 17.3637 秒 |
| `dispatch-cancel-red-confirmed`，新增真实集成用例 | 1 failed；持久命令恢复调度后取消，Task 已 cancelled 但句柄仍存在 | 1 | 25.7019 秒 |
| `cancellation-green`，Coordinator 模块和新增集成用例 | 11 passed | 0 | 24.1443 秒 |
| `related-regression`，85 项组合 | 75 passed / 10 setup errors，错误原因见下 | 1 | 317.3074 秒 |
| `recovery-correct-cwd`，Permit Recovery 模块 | 10 passed | 0 | 39.2384 秒 |

初版红侧测试有两处合同假设被校正，原始日志未删除：已进入协程的用户取消按既有逻辑正常返回，不能强求 `Task.cancelled()`；未授权读取/取消通过原接口隐藏 Run，实际返回 404。校正后红侧都准确失败于句柄残留，且确认红侧使用的测试文件与绿色源码相同，生产实现此时仍为旧版。

集成用例使用真实 FastAPI TestClient 创建任务至正式 Permit，经 HTTP 故障注入留下已接受但尚未创建 Task 的 Dispatch。随后在服务器事件循环、可信主体下恢复提交，并在不让出执行权的情况下调用原 Runtime.cancel 和 Coordinator.cancel，精确覆盖首次 Task 步骤前的切点。这一精确切点通过测试调用服务器服务层注入，不能描述为浏览器恰好制造了该竞态。用例确认未授权取消 404 且事实不变、零 Agent 调用、无活动执行槽、Task 句柄清理，以及 HTTP Dispatch replay/服务重建保持 CANCELLED。旧 Task 与新 Task 的替换单位测试仅测试引用隔离；正式并发拥有权由现有真实 Dispatch 回归覆盖。

## 跨模块验证及目录错误说明

组合命令选择了以下模块/用例，没有运行全量 pytest：

- `apps/agent/tests/test_execution_coordinator.py`
- `apps/agent/tests/test_agentos_c2_dispatch_http.py`
- `apps/agent/tests/test_agentos_c2_dispatch_admission.py`
- `apps/agent/tests/test_agentos_c2_human_review.py`
- `apps/agent/tests/test_agentos_c2_http.py::test_http_legacy_switch_matrix`
- `apps/agent/tests/test_agentos_v2_api.py` 中取消成功/幂等和已完成 Run 拒绝取消两个用例
- `apps/agentOS/tests/components/planner/test_permit_recovery.py`
- `apps/agentOS/tests/runtime/test_app_lifespan.py`

命令通过证据目录的 `run_tests.py` 启动，实际完整参数见 `related-regression.json`，cwd 首次为仓库根目录。该次 75 项通过，包括正式并发派发、ACK 丢失、实际进程死亡、未知外部副作用阻断、取消竞争、审核防重放、Native Dispatch 必要性、Legacy 和服务生命周期。

其余 10 项全部在 Permit Recovery 模块级夹具初始化时出错。确切原因是本轮组合命令 cwd 选错：`test_graph_materialization_audit.py:119` 的 `child_environment()` 从 cwd 解析 `src` 和 `tests/components/planner`，故从仓库根目录启动的子进程报 `ModuleNotFoundError: test_react_loop`。保留首次退出码 1，不把原组合命令改写成通过。

未修改该夹具、子进程断言或业务源码。只将这 10 项在既有预期的 `apps/agentOS` cwd 单独重跑：外层从仓库根目录设置测试进程 cwd 后执行 `tests/components/planner/test_permit_recovery.py -q --disable-warnings --durations=10`，实际配置和命令见 `recovery-correct-cwd.json`。结果 10 passed、退出码 0，覆盖 Checkpoint ACK 丢失、证据损坏、撤权、取消、operator input、审核恢复等。最终同一源码快照下，计划的 **85 个不同用例均有通过证据**；11 项绿色子集与其重叠，不能额外累计。没有伪称原 85 项组合一次全绿。

测试子进程仅隔离三个代理变量，未关闭 TLS 校验。发现 `apps/agent/tests/conftest.py` 会在导入时清理超过一天的 `.tmp-tests` 条目；本轮启动前登记 1082 个既有条目，在测试进程用 Python audit hook 拒绝针对它们的清理操作，原 conftest 的 OSError 处理会跳过。这只保护先前证据，新的测试数据库和目录不在保护集合中；记录见各轮 `*-cleanup-protection.json`。没有修改 conftest 或清空历史目录。

## 源码与历史完整性

| 文件 | 入场 SHA-256 | 结束 SHA-256 |
| --- | --- | --- |
| Coordinator | `a4d3cbef8b7bbf7613fb91e2d2be8e581e11c5724a6671e9e42845612b6cffec` | `e61169e3c1ade5492f83c9080d6591f5a0b93b3f769e09dde1445cd2638530e8` |
| Coordinator 测试 | `b6767dfe41a7336482f948b1a7ea9c2e57ee2847da4762384e530d987a89b33f` | `0dd3d01a0532720a7532fedb1973d104ab78545f2bfc2048036fc1305643993b` |
| Dispatch HTTP 测试 | `52ca88da7dd56155cc678b9536a6a2a697d10d50cc17e2c0ac7006056d880a43` | `9efffec350f307f0f6c5035a425d819a4c327318939b178cd43f933cf22fadf1` |

已有门禁修改完整保留：`scripts/freeze_gate.py` 前后均为 `fb834c0ad42dcfa9c51e1a1dc0ad879f13d4de1493988ab85e6523cd01e96484`；门禁完整性测试前后均为 `06d23d14368d2a35a197e9ff886142b8cb0d4167f29b525adb168a244f9a0f83`。

清点的 108 个正式门禁历史文件及已有审查文档均存在且 SHA-256 不变。历史耗时缓存为 `c02e3af5018b675ef6bb68fb60c0370aa1e21bd5017225afa33d0cb5a5970519`，未清空或更新。`final-verification.json` 保存逐项比较；`int2f-1-only.diff` 只包含本次三份源码/测试文件的差异，不混入之前门禁修复。

`git diff --check HEAD` 退出码 0，暂存区为空；仅有既有换行转换提示。没有修改固定基线、测试映射、300 秒预算、生产配置、前端或数据库。

## 剩余限制及下一项

本次只验收单进程 Coordinator 的 Task 所有权清理和相关控制回归。并未补做真实浏览器、IAM、Provider 或部署验收，不宣称分布式调度、跨库原子性或外部副作用 exactly-once。

研发项达到 SELF-TESTED，V1 未冻结不阻止本项完成。建议下一项优先做真实 IAM 会话撤销与 HTTP 控制/SSE 的一致拒绝验证：以实际可复现证据判断撤销后既有连接和新控制请求的边界，不能预先把尚未验收认定为代码缺失。本轮完成后停止，不自动实施下一项。
