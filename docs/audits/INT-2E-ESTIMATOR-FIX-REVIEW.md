# INT-2E-ESTIMATOR-FIX-REVIEW：运行证据隔离与预算截止

日期：2026-10-26。入场实际 HEAD：`51f4e7193235d7c6c6de0e92cb2af528ddd77fc4`，上一源码提交 `9087071f`；工作区、暂存区干净。本轮不假定旧 GitHub 基线，不推送、不部署，不运行完整正式门禁。

**限定修复自测通过，等待独立复验；V1 继续 BLOCKED。** 完整正式冻结门禁尚未真实通过，定向结果不构成冻结或部署验收许可。

## 调用链与问题

`freeze_gate.main()` 计算源码/选择集 → manifest → 有界 pytest launcher → `RunObservation` → invocation/manifest/全部阶段校验 → `write_report()` → 历史 max/完整剖面发布。原 launcher 已有完整观测校验，不改其算法、测试选择或业务执行合同。

原门禁四类产物使用秒级 UTC 时间戳，两个运行可能互相覆盖。原 `write_report()` 在缓存更新前就冻结 elapsed/finished，仅在剖面替换前检查 deadline，无法证明替换返回或报告落盘时仍在预算内。

## 当前合同

- 每次 main 开始分配 UUID invocationId；artifact ID 为 UTC 秒级时间戳加该完整 UUID。`.log`、`.json`、`.nodeids`、`.observation.json` 同属唯一 ID；提前失败的报告也使用该 ID。缓存发布锁不作为产物隔离替代方案。
- 预算仍是原 300 秒，包含发现、测试、校验、历史缓存更新、剖面发布及最终报告持久写入。成功完成边界明确为 **最终报告原子替换调用返回后，单调时钟检查仍未超过 deadline**；控制台输出为该边界之外的诊断。
- `finished_utc` 与 `elapsed_seconds` 在缓存/剖面处理后、最终报告序列化前一起采样，表示最终状态决策的观测时刻，不伪称是进程退出时间或磁盘调用返回的精确时刻。最终报告 I/O 另有替换前及返回后的硬 deadline 复核；越界后重新采样时间，写入非 PASSED 失败报告。持久报告无法递归包含它自身落盘完成的精确时刻，本合同不作此声称。
- 历史 max 更新后、剖面原子替换后、最终报告替换后均核对 deadline。任何一步失败/超时，恢复本次替换前完整剖面的原始字节；原先没有剖面则移除本次临时结果。失败报告清空 `complete_profile_published`，返回非零。失败记录可在 deadline 之后落盘，以保留真实失败证据。
- 剖面发布、最终报告确认、必要回撤同处既有 OS 缓存锁内；预检读取完整剖面也取得同一锁，避免并发读到尚未完成报告确认的候选。竞争锁失败则 fail-closed。历史 max 仍单调保留，即使最终预算耗尽也不回退 max；它不构成完整剖面。
- 不宣称多文件跨存储事务、任意磁盘故障后的成功持久性，或无法落盘时仍能生成报告。OS 写入失败返回错误，不能作为通过证据。本次覆盖正常异常/超时注入；不新增业务恢复状态机。

## 永久回归与复验

保留既有 70 项完整剖面回归，新增：读锁竞争显式 UNKNOWN；五个持久化切点 × 有/无旧剖面共十项预算故障注入；缓存耗时计入最终时间；同秒并发两次 main 的四类产物隔离及交叉 invocation 观测拒绝。

并发用例以 Barrier 同步 discovery、固定同一 UTC 秒，两个真实线程分别调用父门禁，使用隔离目录与确定性子进程夹具。两份 manifest/log/observation/report 均独立存在；交叉观测不能形成完整剖面。既有真实 launcher 单节点子进程回归继续执行。没有将该小范围测试冒充实际完整选集执行。

命令（cwd `C:\Users\LZX\Desktop\kinlin_ai`）：

```powershell
python -m pytest apps/agentOS/tests/storage/test_freeze_gate_integrity.py -q --disable-warnings --maxfail=1
```

最终数量、时间、退出码和源码 SHA 见下表及本机 `.tmp-tests/int2e-estimator-review/verification.json`。`before.json` 为入场源码/原缓存/历史失败摘要；`invariants.json` 为 AST 常量核验；`tests-final-verified.log` 为最终原始输出。材料均留本机，不提交临时日志或缓存。

中间失败保留：第一轮 31 passed/1 failed（旧 os 夹具未提供原子写入新增调用依赖），第二轮 80 passed/1 failed（并发共享测试目录重复创建），补齐夹具后第三轮 82 passed / 42.80 秒 / exit 0；未删除断言或降低安全条件。

## 保护边界

`SOURCE_TEST_RULES`、`DEFAULT_BUDGET_SECONDS`、固定基线 SHA/aggregate/commit、`EXTERNAL_BASELINE` 与入场 AST 完全一致。原 pytest runner 未修改。原完整剖面算法保留，历史 max 与失败报告不清空。旧 `PR-C2B-INT-2E-V1-FINAL.md` 只加历史快照与当前结论链接，不改历史数字或失败结论。

本轮只改门禁、其完整性测试与必要文档。不修改 AgentOS 业务、真实数据库、compose、生产开关。V1 保持 BLOCKED；不允许以本轮测试替代正式完整冻结门禁，不推送、不部署。

## 最终定向结果与摘要

最终结果：**83 passed，exit 0**。pytest 原始用时见 `tests-final-verified.log`；包装进程 70.794 秒。最终源码测试前后逐字节一致，缓存及历史失败摘要与入场一致。

| 文件 | 最终测试前 = 后 SHA-256 |
| --- | --- |
| scripts/freeze_gate.py | `0358bbbb800be552679b98cede04a829fadbdb27669fe3eb61efba743a065bfb` |
| scripts/freeze_gate_pytest_runner.py | `03bce25689a960b85eec4e718922f66060648036ae2b171d36b8a0a3851e39f6` |
| apps/agentOS/tests/storage/test_freeze_gate_integrity.py | `856c4600b708f6c1c0d3496cca59e3c6255ee2abf21885f5fd31a3dd93f8b332` |
| tmp/freeze_gate/test_durations.json | `c02e3af5018b675ef6bb68fb60c0370aa1e21bd5017225afa33d0cb5a5970519` |
| tmp/freeze_gate/20261026T021224Z.json | `bb49c8114a58093824a7e1089ba4a6f870d9fc316cd8f18bff1394271a715fbd` |

`git diff --check` 通过。本轮本地按门禁修复与永久回归的同一职责固化，提交 SHA 由最终交付消息列明，报告不嵌入自身提交。
