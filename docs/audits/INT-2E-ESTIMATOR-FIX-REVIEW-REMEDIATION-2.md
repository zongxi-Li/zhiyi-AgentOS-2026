# INT-2E-ESTIMATOR-FIX-REVIEW-REMEDIATION-2

2026-10-26。**SELF-TESTED，等待独立验收；V1 保持 BLOCKED**。仅定向测试，不运行全量 pytest、完整正式冻结门禁，不提交、不推送、不部署。

## 入场与保留边界

实际 HEAD：`53eb030023dd2f2c631a222df3786dfd18fc1fa5`。入场已有未提交的 `scripts/freeze_gate.py`、完整性测试及上一轮未跟踪实施记录；全部保留。本轮在这些修改上继续限定修复，不把 HEAD 当作入场源码。入场工作区 SHA 见 `entry.json`；上一轮实施记录原始字节未改。HEAD、暂存区均未变化。

## 红侧：直接读取磁盘与独立 reader

新增四个组合：最终报告替换前/后超时 × 失败报告可写/不可写，全部注入 `restore_profile()` 失败。

关键红态实际执行：最终成功报告 `atomic_json()` 返回并确认磁盘有 PASSED/confirmed=true → 单调时钟推进到 301 → 发布后截止检查失败 → 恢复剖面失败 → 失败报告写入也失败。再次从磁盘读到 PASSED，重建 `load()` / reader、重新读取完整剖面，旧实现返回 **KNOWN**，因此断言失败。

红侧结果：**1 failed、3 passed、89 deselected，exit 1**。没有只检查 main 的内存对象。原始失败日志和源码摘要保留在 `red.log/red.json`。

## 修复：报告提案与不可变提交证据

新增的是同一次门禁的最终证据文件，不是新的业务 Authority、执行状态机或第二套估算算法。完整剖面的来源绑定现有报告，以及同 invocation 的只写一次 receipt：`tmp/freeze_gate/complete_profiles/receipts/{invocation}.json`。

三个层次明确区分：

| 层次 | 合同 |
| --- | --- |
| main 内存结果 | 在提交点前可因预算/存储失败变为失败；不作为重启后的证明 |
| 磁盘主报告 | PASSED/confirmed 字段是待提交提案；缺少 receipt 时不构成成功确认。失败报告无法写入时允许残留该提案，但不得读成有效确认 |
| 预检完整剖面 | 同时验证完整剖面、主报告、receipt 的 invocation/source/manifest/报告 SHA-256 和报告写入后观测的耗时；缺失、损坏、不匹配一律 UNKNOWN |

流程为：原有正式校验/缓存/剖面发布 → 锁退出 → 主报告 atomic_json 实际返回 → 单调 deadline 后验检查 → 生成包含报告原始字节 SHA-256 与 `reportCheckedElapsedSeconds` 的 receipt → 在原 deadline 下暂存、flush/fsync、最后检查并原子替换 receipt。

**提交线性化点是 receipt 的原子替换。** 300 秒常量、映射和固定基线不变。预算判定包含主报告返回后的检查、receipt 序列化/fsync，最后一次单调检查紧邻 receipt 的原子替换之前，必须不超过原 deadline。receipt 中的报告后验耗时也必须有限、非负且不超过本次预算（预算不能超过 300）。不使用主报告写入前采样的 elapsed 冒充后验检查。

提交点前超时，不会发布 receipt；即使所有恢复写入都失败，新建 reader 仍 UNKNOWN。receipt 替换前检查已失败也不会留下有效 receipt。成功提交之后不再用返回后的时钟、控制台输出或包装器异常撤销该决定；否则会再次制造“持久成功、内存失败”。若存储包装器在实际替换完成后抛 OSError，重新读取并核对完全相同的不可变 receipt，确认已提交则返回成功；没有相同 receipt 则继续失败路径。

这里的预算是**提交准入截止**，不是对不可中断单次 OS 原子替换调用返回延迟的额外保证；不可在成功替换后因新的时钟观测把该提交改判失败。本轮明确记录此线性化合同，不把实际操作系统调用耗时的不确定性说成已经消除，也不据此宣称正式 300 秒门禁已通过。独立验收应同时审查这一边界。

receipt 缺失时不依赖补写失败报告、删除候选或恢复旧文件来证明 fail-closed。旧的纯完整剖面仍按原算法校验；带旧 publication 来源但没有 receipt 的记录不能充当新合同确认，返回 UNKNOWN，不迁移或修改真实缓存。

## 永久测试

- 四个组合都实际读取磁盘报告，重建独立 reader；超时发生在最终报告落盘之后时也仍 UNKNOWN。
- 同时注入剖面恢复失败与失败报告写入失败，证明不是依赖回滚写入得到 UNKNOWN。
- receipt 提交前推进时钟到 301：已有 PASSED 提案，但没有 receipt、预检 UNKNOWN。
- receipt 实际提交后再推进时钟并抛包装器异常：main 返回 0、磁盘与 reader 均确认已提交；不会把已提交事实改判失败。
- 已确认报告被修改后，receipt 的报告摘要失配，预检 UNKNOWN。
- 原有完整剖面、预算切点、锁退出失败、并发隔离、真实单节点 launcher 回归继续通过，原测试函数及断言保留。

## 命令、退出码与墙钟

cwd 均为 `C:\Users\LZX\Desktop\kinlin_ai`。完整 argv、原始日志、每次测试前后源码与缓存 SHA 均在忽略目录 `.tmp-tests/int2e-estimator-remediation-2/`。

```powershell
python -m pytest apps/agentOS/tests/storage/test_freeze_gate_integrity.py -q --disable-warnings
```

红侧加 `-k final_report_timeout_with_failed_restore`；绿侧加 `-k "final_report_timeout_with_failed_restore or budget_expiry_during_persistence or lock_release_failure"`。

| 记录 | pytest 结果 | exit | 包装墙钟秒 |
| --- | --- | --- | --- |
| red | 1 failed, 3 passed, 89 deselected in 1.06s | 1 | 4.118 |
| green | 1 failed, 19 passed, 73 deselected in 2.04s | 1 | 4.828 |
| green-2 | 20 passed, 73 deselected in 1.44s | 0 | 3.497 |
| full-integrity | 95 passed in 17.79s | 0 | 20.245 |

首次应用修复时直接写入脚本被本机文件系统拒绝（OSError EINVAL），未改变入场脚本字节，因此该次标为 green 的运行仍为红态（1 failed/19 passed），没有伪报转绿。保留原字节副本后使用同目录临时文件原子替换完成编辑，green-2 转绿。未改 ACL、未删除文件。最终完整性模块 **95 passed / 0 failed / 0 skipped，17.79 秒，exit 0**；包装墙钟约 20.245 秒。

最终测试前后所有记录文件 SHA 一致。`git diff --check HEAD` exit 0；命令、退出码和墙钟见 `checks.json`。没有运行完整正式冻结门禁。

## 完整性与独立复验材料

| 文件 | 入场工作区 SHA-256 | 最终测试前 = 后 SHA-256 |
| --- | --- | --- |
| scripts/freeze_gate.py | `05afd69814b380ae28f46be21c77de2fa0d74f0db10c97c9d5b1027af16d794e` | `39f1175209895dfff0a55f9f482bd8c15e939e2d5241664c2c0d63ed88aadc3c` |
| scripts/freeze_gate_pytest_runner.py | `03bce25689a960b85eec4e718922f66060648036ae2b171d36b8a0a3851e39f6` | `03bce25689a960b85eec4e718922f66060648036ae2b171d36b8a0a3851e39f6` |
| apps/agentOS/tests/storage/test_freeze_gate_integrity.py | `da4676be0e171fb7d9177a73a5e37efc807f9f5816174941bba01e50fbaf1e6b` | `385c6ffb729c54b30e546d987f84559ea02de3611be213ebc9fbc20d9f31806d` |
| docs/audits/INT-2E-ESTIMATOR-FIX-REVIEW-REMEDIATION.md | `053ee12ccdc329d65c73effb3ae4c444eb7344c1686669281c2f2c55fe3985e9` | `053ee12ccdc329d65c73effb3ae4c444eb7344c1686669281c2f2c55fe3985e9` |
| tmp/freeze_gate/test_durations.json | `c02e3af5018b675ef6bb68fb60c0370aa1e21bd5017225afa33d0cb5a5970519` | `c02e3af5018b675ef6bb68fb60c0370aa1e21bd5017225afa33d0cb5a5970519` |
| tmp/freeze_gate/20261026T021224Z.json | `bb49c8114a58093824a7e1089ba4a6f870d9fc316cd8f18bff1394271a715fbd` | `bb49c8114a58093824a7e1089ba4a6f870d9fc316cd8f18bff1394271a715fbd` |

`invariants.json` 证明：`SOURCE_TEST_RULES`、300 秒预算、固定 baseline SHA/aggregate/commit、`EXTERNAL_BASELINE` 未改；`complete_profile()` AST 未改；原测试函数保留；launcher、上一轮文档、真实历史缓存及失败报告摘要未变。`remediation-2-only.patch` 是相对本轮入场工作区的增量，不混入上一轮修改；`gate-entry.py`、`test-entry.py` 为入场源码复验副本。

所有 tmp/cache/log 留在忽略目录。没有覆盖旧失败证据或清空缓存。业务执行合同、数据库、compose、生产开关均未修改。

## 裁决

**SELF-TESTED**，交付本轮限定修复及实际测试证据，等待独立验收。**V1 继续 BLOCKED**：本轮没有正式完整门禁通过的证据，不宣布冻结，不开放生产。无提交、推送、部署；入场并行及上一轮文件继续保留。
