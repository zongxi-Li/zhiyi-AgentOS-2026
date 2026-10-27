# INT-2E-ESTIMATOR-FIX-REVIEW-REMEDIATION

2026-10-26。状态：**SELF-TESTED，等待独立验收；V1 继续 BLOCKED**。未运行完整正式冻结门禁，不宣布 V1 冻结。

## Git 与范围

入场实际 HEAD 和只读核验的 GitHub master 均为 `53eb030023dd2f2c631a222df3786dfd18fc1fa5`（历史包含 `9d028110`）。入场工作区、暂存区干净。没有覆盖并行修改；本轮修改仅为门禁脚本、其完整性测试及本记录。HEAD 保持不变，不暂存、不提交、不推送、不部署，不操作 Gitee。

## 失败反例与修复

### 最终报告切点

旧测试以“freeze_gate 目录下任意 JSON”识别报告，可能误命中 `test_durations.json`；原 harness 对历史更新的空桩也掩盖了该问题。本轮使用真实历史更新函数（只写 pytest 临时目录），以本次 invocation、artifact ID、精确报告路径和最终确认标记匹配切点，明确排除历史缓存及待确认报告。

`report_before` / `report_after` 均先断言历史更新已发生、完整剖面文件已替换且 invocation 对应本次运行、报告已指向本次候选；after 还读取已落盘最终报告，确认写入已经返回且 invocation/候选引用正确，然后才把单调时钟推进至 301 秒。所有原预算断言保留：返回 1、最终非 PASSED、完成时间更新、published 为空、旧剖面原始字节恢复或原先无文件时不残留候选、下次预检行为正确。

### 锁退出异常

原 `with duration_cache_lock()` 内部写入剖面后，锁退出抛 OSError 会直接进入外部错误报告分支，却未恢复候选；该候选仍可被读取为 KNOWN。

新增永久红态：有/无旧剖面 × 正常恢复/恢复失败，旧实现 **4 failed、10 passed、73 deselected，exit 1**。失败分别暴露原始剖面未恢复、恢复失败信息缺失。相同测试在首次修复后 **14 passed、73 deselected，exit 0**。

修复复用现有剖面算法、OS 锁和门禁报告：

1. 新发布剖面增加 `publication` 来源，绑定报告相对路径及 invocation；其 setup/call/teardown 完整剖面算法不变。
2. 锁退出前报告明确为 `PENDING_PROFILE_CONFIRMATION`，确认标记为 false；不能被预检认作成功证据。
3. 仅锁正常退出后，才在既有预算内原子写入 PASSED 最终确认报告。新剖面的读取除原完整性校验外，须核对该确认报告的状态、确认标记、invocation、剖面路径、source 和 manifest。
4. 锁退出异常后重新取得既有锁，验证当前文件仍属本次 invocation 才恢复原始字节，避免覆盖其他发布者。恢复失败记录 `profile_recovery_error` 并写 stderr；可写的失败报告标为失败、published 清空。
5. 恢复失败留下的候选因来源报告未确认而返回 UNKNOWN；重新构造 reader 同样拒绝。旧式无 publication 的合法完整剖面维持兼容，不执行真实缓存迁移。

新增组合故障：锁已释放但退出抛错、恢复也抛错、失败报告同时拒绝写入。测试实际注入写入失败，而非手工伪造报告。此时异常向上抛出（调用进程非零），磁盘上只保留未确认的 PENDING 报告，stderr 明确记录恢复失败，重建预检仍为 UNKNOWN。待确认报告中的候选路径只是诊断引用，不是成功 published 回执。

这不是磁盘故障后必然能恢复的承诺：恢复失败时文件可能仍是候选；无法写失败报告时也不能保证生成新的失败文件。合同是保留未确认证据并拒绝把此候选当作完整有效剖面。报告丢失、损坏或引用不匹配时同样 fail-closed。删除确认报告会使对应新剖面变为 UNKNOWN。未引入业务执行状态机、Authority、Store 或数据库 Schema。

## 命令与证据

全部测试 cwd：`C:\Users\LZX\Desktop\kinlin_ai`。使用实际 Python314 可执行文件，完整 argv、前后 SHA 和原始输出保存在本机忽略目录 `.tmp-tests/int2e-estimator-remediation/`。只找到一个门禁完整性测试模块；其中包括真实 launcher 单节点子进程及并发回归，不执行真实完整选集。

基础命令：

```powershell
python -m pytest apps/agentOS/tests/storage/test_freeze_gate_integrity.py -q --disable-warnings
```

红/绿侧额外选择：`-k "lock_release_failure or budget_expiry_during_persistence"`。

| 证据标签 | pytest 结果 / 用时 | 子进程 exit | 包装墙钟秒 |
| --- | --- | --- | --- |
| red | 4 failed, 10 passed, 73 deselected in 3.97s | 1 | 9.135 |
| green | 14 passed, 73 deselected in 2.76s | 0 | 15.769 |
| full-integrity | 87 passed in 14.47s | 0 | 17.171 |
| final-integrity | 89 passed in 11.60s | 0 | 13.053 |
| final | 89 passed in 11.58s | 0 | 13.011 |
| verified | 89 passed in 11.56s | 0 | 12.978 |
| final-verified | 89 passed in 11.61s | 0 | 13.089 |

首次完整测试为 87 项；加入真实失败报告写入故障后为 89 项。中间完整通过记录分别对应当时源码；以 `final-verified.json/.log` 为最终快照，**89 passed / 0 failed / 0 skipped，11.61 秒，exit 0**。后续源码未修改。测试前后摘要逐文件相同。未运行全量 pytest 或 300 秒正式门禁。

`git diff --check HEAD` 最终 exit 0；初次发现文件尾多余空行导致 exit 1，已修正，未隐瞒该中间检查。`checks.json` 保留最终 diff 检查和 GitHub 只读 ls-remote 的命令、退出码及墙钟。

## 源码和缓存保护

`SOURCE_TEST_RULES`、300 秒预算、固定基线 SHA/aggregate/commit、`EXTERNAL_BASELINE` 与 HEAD 的 AST 一致；`complete_profile()` AST 不变，原测试函数全部保留。launcher 未改。证明见 `invariants.json`。

| 文件 | 入场 SHA-256 | 最终测试前 = 后 SHA-256 |
| --- | --- | --- |
| scripts/freeze_gate.py | `0358bbbb800be552679b98cede04a829fadbdb27669fe3eb61efba743a065bfb` | `05afd69814b380ae28f46be21c77de2fa0d74f0db10c97c9d5b1027af16d794e` |
| scripts/freeze_gate_pytest_runner.py | `03bce25689a960b85eec4e718922f66060648036ae2b171d36b8a0a3851e39f6` | `03bce25689a960b85eec4e718922f66060648036ae2b171d36b8a0a3851e39f6` |
| apps/agentOS/tests/storage/test_freeze_gate_integrity.py | `856c4600b708f6c1c0d3496cca59e3c6255ee2abf21885f5fd31a3dd93f8b332` | `da4676be0e171fb7d9177a73a5e37efc807f9f5816174941bba01e50fbaf1e6b` |
| tmp/freeze_gate/test_durations.json | `c02e3af5018b675ef6bb68fb60c0370aa1e21bd5017225afa33d0cb5a5970519` | `c02e3af5018b675ef6bb68fb60c0370aa1e21bd5017225afa33d0cb5a5970519` |
| tmp/freeze_gate/20261026T021224Z.json | `bb49c8114a58093824a7e1089ba4a6f870d9fc316cd8f18bff1394271a715fbd` | `bb49c8114a58093824a7e1089ba4a6f870d9fc316cd8f18bff1394271a715fbd` |

缓存和历史失败报告摘要与入场一致，不清空、不覆盖。原有完整剖面算法及旧缓存兼容保留；没有修改业务执行合同、测试映射或固定 manifest。生产数据库、compose、生产开关均未触及。

独立材料：`entry.json`、`red.json/.log`、`green.json/.log`、`final-verified.json/.log`、`checks.json`、`invariants.json`、`remediation.patch`。临时缓存、日志和补丁留在忽略目录，不入库；实施记录作为未提交文件交付。

## 裁决

**SELF-TESTED**：两项限定修复及定向回归完成，等待独立复验。**V1 继续 BLOCKED**：正式完整冻结门禁尚未真实通过。不得用本轮定向测试宣告 V1 冻结或生产 READY。无新增提交，无推送、部署或开关开放。
