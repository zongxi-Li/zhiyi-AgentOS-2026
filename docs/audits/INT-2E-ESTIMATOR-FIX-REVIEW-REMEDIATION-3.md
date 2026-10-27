# INT-2E-ESTIMATOR-FIX-REVIEW-REMEDIATION-3

日期：2026-10-26。**SELF-TESTED，等待独立复验；V1 保持 BLOCKED。** 本轮不授权、不宣布最终冻结。

## 入场保护

实际 HEAD 为 `53eb030023dd2f2c631a222df3786dfd18fc1fa5`，暂存区为空。入场有门禁脚本、完整性测试的上一轮未提交修改，以及 REMEDIATION / REMEDIATION-2 两份未跟踪记录；均保留。本轮以实际工作区为基准，没有用 HEAD 或远程覆盖源码。

`.tmp-tests/int2e-estimator-remediation-3/entry.json` 记录入场 HEAD、源码、旧报告、真实缓存与历史失败报告 SHA-256；`gate-entry.py`、`test-entry.py` 保存本轮入场工作区原始字节。所有旧证据保留不覆盖。HEAD 与暂存区未变化，不提交、不推送、不部署。

## 红侧反例

新增测试调用真实 reader，并先通过门禁父流程的隔离夹具生成真实 JSON 剖面、报告和回执。执行子进程使用既有确定性测试夹具；来源查询、落盘和 reader 不以返回值桩替代。

- 修改 `processElapsedSeconds`，同步用原 `complete_profile()` 重建 `estimateSeconds` 等派生值，保持内部自洽。
- 修改 observation call 耗时，同步重算节点耗时、总和和 estimate。
- 修改 publication 附加字段，或仅在文件末尾增加一个空格。
- 保持报告与回执原始字节不变，再构造独立 gate/reader。

旧实现对这些自洽/原始字节篡改返回 KNOWN。红侧 **8 failed、5 passed、95 deselected，exit 1**：其中七项为篡改或摘要字段未受校验；另一项为合法发布记录没有写入新要求的 `profileSha256`。日志 `red.log` 与 `red.json` 完整保留，未用 main 的内存对象冒充 reader 证据。

## 最小实现与读取顺序

修改 `scripts/freeze_gate.py`：

1. 完整剖面原子发布后，仍在既有缓存锁内读取其原始文件字节并计算 SHA-256，保存至本次调用局部变量；稍后将该摘要作为 `profileSha256` 写入现有不可变 receipt。摘要覆盖全部剖面字节（包括 publication），不将 receipt 内容写回剖面，避免循环依赖。
2. reader 只读取一次完整剖面，得到 `raw_profile`，计算其原始摘要；先在既有 receipts 目录读取回执，严格匹配小写 64 位十六进制摘要。没有匹配摘要时，立即 UNKNOWN，尚不解析剖面 JSON。
3. 摘要匹配后才执行 `json.loads(raw_profile)`，使用刚才哈希的同一 bytes 对象；再按 publication 引用选择同一次预读到的匹配回执，执行原有 report SHA-256、invocation、source、manifest、状态、预算和完整性重算。
4. 缺失/格式错误/不匹配摘要，损坏或缺失回执，错误关联字段均 UNKNOWN。没有回执绑定的旧剖面不再被当作 KNOWN；不修改、不补签、不迁移真实旧缓存。

回执查找是既有目录的只读发现，不新增 Store、索引、执行状态机或第二套估算算法。原子提交线性化点、提交前后异常处理、恢复与退出码合同保留；本轮不修改上一轮的预算裁决语义。

## 永久回归

新增 13 项真实 reader 案例：完整一致时 KNOWN；process/observation 自洽篡改、publication 修改、空白字节变化、摘要缺失/格式错误/不匹配、回执缺失/损坏、invocation/source/manifest 错配时 UNKNOWN。篡改剖面的案例均断言原报告及回执未改。

另增两项读取顺序/TOCTOU 回归：

- 原始字节改变但回执不变：监测 `json.loads`，断言未核验的剖面根本没有被解析。
- 捕获剖面字节后，模拟磁盘内容立即变化：断言 profile 只读一次，哈希与 JSON 解析使用同一个捕获 bytes 对象，返回值对应这一份已核验快照，不重新读取另一份内容。

现有预算、报告篡改、恢复失败、并发、receipt 提交前后异常继续覆盖。原先直接写裸 JSON 的正向旧剖面夹具补齐报告及原始字节 receipt，使其满足新的有效输入合同；**原测试函数与原 assert AST 全部保留**，没有降低断言或缩减选择。

## 实际命令与结果

cwd：`C:\Users\LZX\Desktop\kinlin_ai`。命令由 `.tmp-tests/int2e-estimator-remediation-3/run.py` 启动实际 Python314；每次 argv、cwd、真实退出码、墙钟、前后 SHA 均保存在同名 JSON，原始输出在同名 log。

```powershell
python -m pytest apps/agentOS/tests/storage/test_freeze_gate_integrity.py -q --disable-warnings
```

红侧加 `-k receipt_binds_exact_profile`；绿侧选择新增绑定测试及原有 receipt/报告/预算/恢复回归（精确表达式见 `green.json`）。

| 证据标签 | pytest 结果 | exit | 包装墙钟秒 |
| --- | --- | --- | --- |
| red | 8 failed, 5 passed, 95 deselected in 1.78s | 1 | 4.201 |
| green | 35 passed, 73 deselected in 2.80s | 0 | 5.752 |
| full-integrity | 110 passed in 16.27s | 0 | 18.390 |

最终完整模块 **110 passed / 0 failed / 0 skipped，16.27 秒，exit 0**。测试前后源码及记录文件 SHA-256 完全一致。没有运行全量 pytest 或正式完整冻结门禁。`git diff --check HEAD` exit 0；`checks.json` 记录 diff、status、HEAD 与暂存区检查命令、退出码和墙钟。

## 源码和缓存摘要

| 文件 | 入场工作区 SHA-256 | 最终测试前 = 后 SHA-256 |
| --- | --- | --- |
| scripts/freeze_gate.py | `39f1175209895dfff0a55f9f482bd8c15e939e2d5241664c2c0d63ed88aadc3c` | `fb834c0ad42dcfa9c51e1a1dc0ad879f13d4de1493988ab85e6523cd01e96484` |
| scripts/freeze_gate_pytest_runner.py | `03bce25689a960b85eec4e718922f66060648036ae2b171d36b8a0a3851e39f6` | `03bce25689a960b85eec4e718922f66060648036ae2b171d36b8a0a3851e39f6` |
| apps/agentOS/tests/storage/test_freeze_gate_integrity.py | `385c6ffb729c54b30e546d987f84559ea02de3611be213ebc9fbc20d9f31806d` | `0b73609e2d6dc8d1729628ca0d3e725aad69b0811112a5aa852b86548101d5c7` |
| docs/audits/INT-2E-ESTIMATOR-FIX-REVIEW-REMEDIATION.md | `053ee12ccdc329d65c73effb3ae4c444eb7344c1686669281c2f2c55fe3985e9` | `053ee12ccdc329d65c73effb3ae4c444eb7344c1686669281c2f2c55fe3985e9` |
| docs/audits/INT-2E-ESTIMATOR-FIX-REVIEW-REMEDIATION-2.md | `b5f2cc574428ca03d9bef2fb0cad23e5076877e58a3efe66d1d4aee4e9d50631` | `b5f2cc574428ca03d9bef2fb0cad23e5076877e58a3efe66d1d4aee4e9d50631` |
| tmp/freeze_gate/test_durations.json | `c02e3af5018b675ef6bb68fb60c0370aa1e21bd5017225afa33d0cb5a5970519` | `c02e3af5018b675ef6bb68fb60c0370aa1e21bd5017225afa33d0cb5a5970519` |
| tmp/freeze_gate/20261026T021224Z.json | `bb49c8114a58093824a7e1089ba4a6f870d9fc316cd8f18bff1394271a715fbd` | `bb49c8114a58093824a7e1089ba4a6f870d9fc316cd8f18bff1394271a715fbd` |

`invariants.json` 证明固定基线 SHA/aggregate/commit、`SOURCE_TEST_RULES`、`EXTERNAL_BASELINE`、300 秒预算未改，`complete_profile()` AST 不变，原有测试函数及 assert 全部保留。launcher、两份上轮报告、历史 max 缓存和旧失败报告与入场字节一致。

`remediation-3-only.patch` 为相对本轮入场工作区的增量，仅含本轮脚本与测试改动；不混入上两轮未提交修复。临时副本、日志、缓存不入库。实施记录新增为未提交文件。

## 剩余边界与裁决

- 回执发现扫描既有 receipts 目录；大量历史回执的查找性能和容量未验收。本轮不新增索引或缓存来扩大任务范围。
- SHA-256 提供关联完整性，不是签名；不声称抵御有权限同时重写所有报告、回执与剖面的攻击者。
- 单次读取校验的是捕获快照，不声称锁能阻止不遵守锁的外部程序在之后修改文件。
- 缺少新摘要的旧记录明确 UNKNOWN；原文件保留，不把它视为零耗时或自动补签。
- 仍未运行完整正式冻结门禁；既有生产、容量和原生宿主边界保持未验证。上一轮线性化/截止边界待独立验收，本轮不借定向通过宣布冻结。

本轮仅达到 **SELF-TESTED，等待独立复验**。**V1 保持 BLOCKED**。未提交、未推送、未部署；未清缓存、改预算、改映射、改生产开关或覆盖旧证据。
